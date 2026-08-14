from __future__ import annotations

import json
import unittest
from pathlib import Path

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


class FlaskTests(unittest.TestCase):
    def setUp(self) -> None:
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_home_page_uses_original_interface_and_client_bridge(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"(read: \"hammer\")", response.data)
        self.assertIn(b'id="input-link"', response.data)
        self.assertIn(b"static/app.js", response.data)

    def test_fragment_decoder_api_resolves_reference_payload(self) -> None:
        response = self.client.post(
            "/api/decompress",
            json={"payload": "O,QnpHuemsiV2e_BfyZNRqhI!", "mode": "auto"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["url"], "https://example.com/docs/guide?ref=ha#intro")

    def test_fragment_resolver_redirects_reference_payload(self) -> None:
        response = self.client.get(
            "/resolve?payload=O%2CQnpHuemsiV2e_BfyZNRqhI%21",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://example.com/docs/guide?ref=ha#intro")

    def test_qr_api_and_qr_redirect(self) -> None:
        url = "https://example.com/docs/guide?ref=ha#intro"
        response = self.client.post("/api/qr", json={"url": url, "correction_level": 1})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["image"].startswith("data:image/png;base64,"))
        payload = response.json["payload"]
        redirect_response = self.client.get(f"/{payload}", follow_redirects=False)
        self.assertEqual(redirect_response.status_code, 302)
        self.assertEqual(redirect_response.headers["Location"], url)

    def test_healthcheck(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "codec": "python"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
