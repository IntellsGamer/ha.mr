"""ASGI entry point for ha.mr.

The application only handles HTTP, rendering, and response assembly. Compression,
decoding, and QR work run in a bounded process pool so they never block the
asyncio event loop handling other requests.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    CPU_POOL.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="ha.mr", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    value = value.strip()
    if len(value) > MAX_INPUT_CHARS:
        raise HTTPException(status_code=413, detail=f"{field} exceeds {MAX_INPUT_CHARS} characters")
    return value


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the ha.mr-style page; fragments are resolved by the browser bridge."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/compress")
async def api_compress(request: Request) -> JSONResponse:
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
    body = await _json(request)
    payload = _text(body.get("payload", ""), field="payload")
    mode = body.get("mode", "auto")
    if not isinstance(mode, str):
        raise HTTPException(status_code=422, detail="mode must be a string")
    return JSONResponse({"url": await _cpu(decode_payload, payload, mode)})


@app.get("/resolve")
async def resolve_fragment_payload(request: Request, payload: str = "") -> RedirectResponse:
    """Receive browser-only fragments through a query bridge and redirect once decoded."""
    destination = await _cpu(decode_payload, _text(payload.replace(" ", ""), field="payload"), "auto")
    return RedirectResponse(destination, status_code=302)


@app.post("/api/qr")
async def api_qr(request: Request) -> JSONResponse:
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
async def resolve_qr_payload(payload: str) -> RedirectResponse | PlainTextResponse:
    """Decode QR-mode path payloads without creating server-side link state."""
    try:
        destination = await _cpu(decode_payload, _text(payload, field="payload"), "qr")
    except HTTPException:
        return PlainTextResponse("Unknown ha.mr payload", status_code=404)
    return RedirectResponse(destination, status_code=302)
