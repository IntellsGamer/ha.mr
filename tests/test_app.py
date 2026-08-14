from __future__ import annotations

import json
import unittest

import app as app_module
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from ha_mr.codec import ASCII_ALPHABET, QR_ALPHABET, compress, decompress


class CodecTests(unittest.TestCase):
    def test_round_trips_common_urls(self) -> None:
        urls = [
            "https://example.com/",
            "http://www.example.org:8080/api/v1/items-42?sort=desc&limit=10#section-2",
            "https://docs.python.org/3/library/urllib.parse.html",
            "example.net/Index_123",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(decompress(compress(url, ASCII_ALPHABET), ASCII_ALPHABET), self._normalised(url))

    def test_upstream_reference_vector(self) -> None:
        vectors = json.loads((Path(__file__).parent / "reference_vectors.json").read_text())
        for vector in vectors:
            with self.subTest(url=vector["url"]):
                self.assertEqual(compress(vector["url"], ASCII_ALPHABET), vector["ascii_payload"])
                self.assertEqual(decompress(vector["ascii_payload"], ASCII_ALPHABET), vector["url"])

    def test_qr_mode_round_trip(self) -> None:
        url = "https://example.com/docs/guide?ref=ha#intro"
        payload = compress(url, QR_ALPHABET)
        self.assertTrue(set(payload).issubset(set(QR_ALPHABET)))
        self.assertEqual(decompress(payload, QR_ALPHABET), url)

    @staticmethod
    def _normalised(url: str) -> str:
        value = url if "://" in url else f"http://{url}"
        return value[:-1] if value.endswith("/") and value.count("/") == 3 else value


class ASGIApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_home_page_uses_original_interface_and_client_bridge(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("(read: \"hammer\")", response.text)
        self.assertIn('id="input-link"', response.text)
        self.assertIn("static/app.js", response.text)

    def test_index_negotiates_terminal_json_and_crawler_responses(self) -> None:
        terminal = self.client.get("/", headers={"user-agent": "curl/8.7.1", "accept": "*/*"})
        self.assertEqual(terminal.status_code, 200)
        self.assertTrue(terminal.headers["content-type"].startswith("text/plain"))
        self.assertIn("self-contained URL compressor", terminal.text)

        json_response = self.client.get("/", headers={"accept": "application/json"})
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.json()["service"], "ha.mr")

        crawler = self.client.get("/", headers={"user-agent": "Discordbot/2.0", "accept": "text/html"})
        self.assertEqual(crawler.status_code, 200)
        self.assertTrue(crawler.headers["content-type"].startswith("text/html"))
        self.assertIn('property="og:title"', crawler.text)
        self.assertIn("ha.mr — self-contained URL compressor", crawler.text)

        for search_bot in ("Googlebot/2.1", "bingbot/2.0"):
            with self.subTest(user_agent=search_bot):
                normal_page = self.client.get("/", headers={"user-agent": search_bot, "accept": "text/html"})
                self.assertEqual(normal_page.status_code, 200)
                self.assertIn('id="input-link"', normal_page.text)
                self.assertNotIn('property="og:title"', normal_page.text)

    def test_qr_short_link_negotiates_terminal_json_and_crawler_responses(self) -> None:
        destination = "https://example.com/docs/guide?ref=ha#intro"
        payload = compress(destination, QR_ALPHABET)
        path = f"/{payload}"

        browser = self.client.get(path, follow_redirects=False)
        self.assertEqual(browser.status_code, 302)
        self.assertEqual(browser.headers["location"], destination)

        terminal = self.client.get(path, headers={"user-agent": "curl/8.7.1", "accept": "*/*"})
        self.assertEqual(terminal.status_code, 200)
        self.assertTrue(terminal.headers["content-type"].startswith("text/plain"))
        self.assertEqual(terminal.text.splitlines(), [destination])

        json_response = self.client.get(path, headers={"accept": "application/json"})
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.json(), {"url": destination})

        crawler = self.client.get(path, headers={"user-agent": "Discordbot/2.0", "accept": "text/html"})
        self.assertEqual(crawler.status_code, 200)
        self.assertTrue(crawler.headers["content-type"].startswith("text/html"))
        self.assertIn('property="og:title"', crawler.text)
        self.assertIn(destination, crawler.text)
        self.assertEqual(crawler.headers["vary"], "Accept, User-Agent")

    def test_offline_worker_is_root_scoped_and_no_cache(self) -> None:
        response = self.client.get("/offline_sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["service-worker-allowed"], "/")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertIn("ha-mr-offline-", response.text)

    def test_server_codec_rate_limiter_rejects_excess_burst(self) -> None:
        original = (
            app_module.SERVER_RATE_LIMIT_REQUESTS,
            app_module.SERVER_RATE_LIMIT_BURST,
            app_module.SERVER_RATE_LIMIT_REFILL_PER_SECOND,
        )
        try:
            app_module.SERVER_RATE_LIMIT_REQUESTS = 2
            app_module.SERVER_RATE_LIMIT_BURST = 2
            app_module.SERVER_RATE_LIMIT_REFILL_PER_SECOND = 0.0001
            app_module.SERVER_RATE_LIMIT_BUCKETS.clear()
            body = {"payload": "O,QnpHuemsiV2e_BfyZNRqhI!", "mode": "auto"}
            self.assertEqual(self.client.post("/api/decompress", json=body).status_code, 200)
            self.assertEqual(self.client.post("/api/decompress", json=body).status_code, 200)
            limited = self.client.post("/api/decompress", json=body)
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.headers["retry-after"], "10000")
            self.assertEqual(limited.headers["x-ratelimit-limit"], "2")
        finally:
            (
                app_module.SERVER_RATE_LIMIT_REQUESTS,
                app_module.SERVER_RATE_LIMIT_BURST,
                app_module.SERVER_RATE_LIMIT_REFILL_PER_SECOND,
            ) = original
            app_module.SERVER_RATE_LIMIT_BUCKETS.clear()

    def test_fragment_decoder_api_resolves_reference_payload(self) -> None:
        response = self.client.post(
            "/api/decompress",
            json={"payload": "O,QnpHuemsiV2e_BfyZNRqhI!", "mode": "auto"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "https://example.com/docs/guide?ref=ha#intro")

    def test_fragment_resolver_redirects_reference_payload(self) -> None:
        response = self.client.get(
            "/resolve?payload=O%2CQnpHuemsiV2e_BfyZNRqhI%21",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://example.com/docs/guide?ref=ha#intro")

    def test_qr_api_and_qr_redirect(self) -> None:
        url = "https://example.com/docs/guide?ref=ha#intro"
        response = self.client.post("/api/qr", json={"url": url, "correction_level": 1})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["image"].startswith("data:image/png;base64,"))
        payload = response.json()["payload"]
        redirect_response = self.client.get(f"/{payload}", follow_redirects=False)
        self.assertEqual(redirect_response.status_code, 302)
        self.assertEqual(redirect_response.headers["location"], url)

    def test_healthcheck_reports_asgi_runtime(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        health = response.json()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["codec"], "python")
        self.assertEqual(health["runtime"], "asgi")
        self.assertGreaterEqual(health["cpu_workers"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
