"""ASGI entry point for ha.mr.

The application only handles HTTP, rendering, and response assembly. Compression,
decoding, and QR work run in a bounded process pool so they never block the
asyncio event loop handling other requests.
"""

from __future__ import annotations

import asyncio
import html
import os
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from multiprocessing import get_context
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ha_mr.codec import CodecError
from ha_mr.service import compress_payload, decode_payload, qr_result

ROOT = Path(__file__).resolve().parent
MAX_INPUT_CHARS = int(os.environ.get("HA_MR_MAX_INPUT_CHARS", "65536"))
CPU_WORKERS = max(1, int(os.environ.get("HA_MR_CPU_WORKERS", str(min(4, os.cpu_count() or 1)))))
CPU_QUEUE_LIMIT = max(CPU_WORKERS, int(os.environ.get("HA_MR_CPU_QUEUE_LIMIT", str(CPU_WORKERS * 8))))
CPU_POOL = ProcessPoolExecutor(max_workers=CPU_WORKERS, mp_context=get_context("spawn"))
CPU_SLOTS = asyncio.Semaphore(CPU_QUEUE_LIMIT)
SERVER_RATE_LIMIT_REQUESTS = max(1, int(os.environ.get("HA_MR_SERVER_RATE_LIMIT_REQUESTS", "60")))
SERVER_RATE_LIMIT_WINDOW_SECONDS = max(1.0, float(os.environ.get("HA_MR_SERVER_RATE_LIMIT_WINDOW_SECONDS", "60")))
SERVER_RATE_LIMIT_BURST = max(1, int(os.environ.get("HA_MR_SERVER_RATE_LIMIT_BURST", "20")))
SERVER_RATE_LIMIT_BURST = min(SERVER_RATE_LIMIT_BURST, SERVER_RATE_LIMIT_REQUESTS)
SERVER_RATE_LIMIT_REFILL_PER_SECOND = SERVER_RATE_LIMIT_REQUESTS / SERVER_RATE_LIMIT_WINDOW_SECONDS
SERVER_RATE_LIMIT_MAX_CLIENTS = max(100, int(os.environ.get("HA_MR_SERVER_RATE_LIMIT_MAX_CLIENTS", "10000")))
SERVER_RATE_LIMIT_BUCKETS: dict[str, tuple[float, float]] = {}
SERVER_RATE_LIMIT_LOCK = Lock()
_CRAWLER_USER_AGENT_MARKERS = (
    "discordbot",
    "discord/",
    "slackbot",
    "twitterbot",
    "facebookexternalhit",
    "facebot",
    "linkedinbot",
    "telegrambot",
    "whatsapp",
    "yandexbot",
    "duckduckbot",
    "applebot",
    "baiduspider",
    "crawler",
    "spider",
    "preview",
)
_TERMINAL_USER_AGENT_MARKERS = (
    "curl/",
    "wget/",
    "httpie/",
    "python-requests/",
    "go-http-client/",
    "powershell/",
)
_RESPONSE_VARY_HEADERS = {"Vary": "Accept, User-Agent"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    CPU_POOL.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="ha.mr", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "").lower()


def _is_crawler(request: Request) -> bool:
    user_agent = _user_agent(request)
    return any(marker in user_agent for marker in _CRAWLER_USER_AGENT_MARKERS)


def _is_terminal_client(request: Request) -> bool:
    user_agent = _user_agent(request)
    return any(marker in user_agent for marker in _TERMINAL_USER_AGENT_MARKERS)


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def _crawler_preview(request: Request, *, title: str, description: str, destination: str | None = None) -> HTMLResponse:
    """Return a compact crawler-only document with standards-compatible OG metadata."""
    canonical_url = f"{_base_url(request)}{request.url.path}"
    escaped_title = html.escape(title, quote=True)
    escaped_description = html.escape(description[:512], quote=True)
    escaped_canonical = html.escape(canonical_url, quote=True)
    escaped_destination = html.escape(destination or canonical_url, quote=True)
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{escaped_title}</title>"
        f"<meta property=\"og:title\" content=\"{escaped_title}\">"
        f"<meta property=\"og:description\" content=\"{escaped_description}\">"
        f"<meta property=\"og:type\" content=\"website\">"
        f"<meta property=\"og:url\" content=\"{escaped_canonical}\">"
        f"<meta name=\"twitter:card\" content=\"summary\">"
        f"<meta name=\"twitter:title\" content=\"{escaped_title}\">"
        f"<meta name=\"twitter:description\" content=\"{escaped_description}\">"
        "</head><body>"
        f"<p>{escaped_title}</p><p>{escaped_description}</p>"
        f"<a href=\"{escaped_destination}\">Continue</a>"
        "</body></html>"
    )
    return HTMLResponse(document, headers=_RESPONSE_VARY_HEADERS)


def _destination_response(request: Request, destination: str) -> RedirectResponse | JSONResponse | PlainTextResponse | HTMLResponse:
    """Negotiate decoded short-link responses without changing normal browser behavior."""
    if _wants_json(request):
        return JSONResponse({"url": destination}, headers=_RESPONSE_VARY_HEADERS)
    if _is_crawler(request):
        return _crawler_preview(
            request,
            title="ha.mr link preview",
            description=destination,
            destination=destination,
        )
    if _is_terminal_client(request):
        return PlainTextResponse(f"{destination}\n", headers=_RESPONSE_VARY_HEADERS)
    return RedirectResponse(destination, status_code=302, headers=_RESPONSE_VARY_HEADERS)


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    value = value.strip()
    if len(value) > MAX_INPUT_CHARS:
        raise HTTPException(status_code=413, detail=f"{field} exceeds {MAX_INPUT_CHARS} characters")
    return value


async def _enforce_server_rate_limit(request: Request) -> None:
    """Apply a small in-memory token bucket to server-side codec work only."""
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with SERVER_RATE_LIMIT_LOCK:
        if client_key not in SERVER_RATE_LIMIT_BUCKETS and len(SERVER_RATE_LIMIT_BUCKETS) >= SERVER_RATE_LIMIT_MAX_CLIENTS:
            stale_before = now - SERVER_RATE_LIMIT_WINDOW_SECONDS * 2
            for key, (_, touched) in list(SERVER_RATE_LIMIT_BUCKETS.items()):
                if touched < stale_before:
                    SERVER_RATE_LIMIT_BUCKETS.pop(key, None)
            if len(SERVER_RATE_LIMIT_BUCKETS) >= SERVER_RATE_LIMIT_MAX_CLIENTS:
                oldest_key = min(SERVER_RATE_LIMIT_BUCKETS, key=lambda key: SERVER_RATE_LIMIT_BUCKETS[key][1])
                SERVER_RATE_LIMIT_BUCKETS.pop(oldest_key, None)
        tokens, updated_at = SERVER_RATE_LIMIT_BUCKETS.get(client_key, (float(SERVER_RATE_LIMIT_BURST), now))
        tokens = min(
            float(SERVER_RATE_LIMIT_BURST),
            tokens + (now - updated_at) * SERVER_RATE_LIMIT_REFILL_PER_SECOND,
        )
        if tokens < 1:
            retry_after = max(1, int((1 - tokens) / SERVER_RATE_LIMIT_REFILL_PER_SECOND) + 1)
            SERVER_RATE_LIMIT_BUCKETS[client_key] = (tokens, now)
            raise HTTPException(
                status_code=429,
                detail="Server-side codec rate limit reached. Please retry shortly or use client-side V26.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(SERVER_RATE_LIMIT_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                },
            )
        SERVER_RATE_LIMIT_BUCKETS[client_key] = (tokens - 1, now)


async def _cpu(function: Callable[..., Any], *args: Any) -> Any:
    """Run bounded CPU work outside the event loop and preserve codec errors."""
    async with CPU_SLOTS:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(CPU_POOL, function, *args)
        except CodecError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body must be an object")
    return body


@app.get("/offline_sw.js", include_in_schema=False)
async def offline_service_worker() -> FileResponse:
    """Serve the offline-first worker at root scope."""
    return FileResponse(
        ROOT / "offline_sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/", response_class=HTMLResponse, response_model=None)
async def index(request: Request) -> HTMLResponse | JSONResponse | PlainTextResponse:
    """Serve the normal page, or lightweight negotiated metadata for non-browsers."""
    if _wants_json(request):
        return JSONResponse(
            {"service": "ha.mr", "description": "Self-contained URL compressor. No redirect database."},
            headers=_RESPONSE_VARY_HEADERS,
        )
    if _is_crawler(request):
        return _crawler_preview(
            request,
            title="ha.mr — self-contained URL compressor",
            description="Self-contained links. No redirect database.",
        )
    if _is_terminal_client(request):
        return PlainTextResponse(
            "ha.mr — self-contained URL compressor. No redirect database.\n",
            headers=_RESPONSE_VARY_HEADERS,
        )
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/compress")
async def api_compress(request: Request) -> JSONResponse:
    await _enforce_server_rate_limit(request)
    body = await _json(request)
    url = _text(body.get("url", ""), field="url")
    mode = body.get("mode", "ascii")
    if not isinstance(mode, str):
        raise HTTPException(status_code=422, detail="mode must be a string")
    payload = await _cpu(compress_payload, url, mode)
    link = f"{_base_url(request).upper()}/{payload}" if mode == "qr" else f"{_base_url(request)}#{payload}"
    return JSONResponse({"payload": payload, "link": link, "mode": mode})


@app.post("/api/decompress")
async def api_decompress(request: Request) -> JSONResponse:
    await _enforce_server_rate_limit(request)
    body = await _json(request)
    payload = _text(body.get("payload", ""), field="payload")
    mode = body.get("mode", "auto")
    if not isinstance(mode, str):
        raise HTTPException(status_code=422, detail="mode must be a string")
    return JSONResponse({"url": await _cpu(decode_payload, payload, mode)})


@app.get("/resolve", response_model=None)
async def resolve_fragment_payload(request: Request, payload: str = "") -> RedirectResponse | JSONResponse | PlainTextResponse | HTMLResponse:
    """Receive browser-only fragments through a query bridge and negotiate the decoded response."""
    await _enforce_server_rate_limit(request)
    destination = await _cpu(decode_payload, _text(payload.replace(" ", ""), field="payload"), "auto")
    return _destination_response(request, destination)


@app.post("/api/qr")
async def api_qr(request: Request) -> JSONResponse:
    await _enforce_server_rate_limit(request)
    body = await _json(request)
    url = _text(body.get("url", ""), field="url")
    try:
        correction_level = int(body.get("correction_level", 1))
    except (TypeError, ValueError):
        correction_level = 1
    return JSONResponse(await _cpu(qr_result, url, _base_url(request), correction_level))


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "codec": "python",
        "runtime": "asgi",
        "cpu_workers": CPU_WORKERS,
        "queue_limit": CPU_QUEUE_LIMIT,
    })


@app.get("/{payload:path}", response_model=None)
async def resolve_qr_payload(request: Request, payload: str) -> RedirectResponse | JSONResponse | PlainTextResponse | HTMLResponse:
    """Decode QR-mode path payloads without creating server-side link state."""
    await _enforce_server_rate_limit(request)
    try:
        destination = await _cpu(decode_payload, _text(payload, field="payload"), "qr")
    except HTTPException:
        return PlainTextResponse("Unknown ha.mr payload", status_code=404)
    return _destination_response(request, destination)
