from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app import app
from ha_mr.codec import (
    ASCII_ALPHABET,
    CJK_ALPHABET,
    EMOJI_ALPHABET,
    compress_adaptive,
    decompress_adaptive,
    infer_alphabet,
    is_v1_payload,
    payload_symbol_count,
)


LONG_TAIL_URL = (
    "https://accounts.google.com/ServiceLogin?passive=1209600&continue="
    "https://www.google.com/history/optout?hl%3Den%26nzb%3D1&followup="
    "https://www.google.com/history/optout?hl%3Den%26nzb%3D1&hl=en&ec=GAZAjQI"
)


class AdaptiveCodecTests(unittest.TestCase):
    def test_legacy_compatible_payload_stays_decodable(self) -> None:
        url = "https://www.youtube.com/"
        payload = compress_adaptive(url, ASCII_ALPHABET)
        self.assertFalse(is_v1_payload(payload, ASCII_ALPHABET))
        self.assertEqual(decompress_adaptive(payload, ASCII_ALPHABET), "https://www.youtube.com")

    def test_v1_handles_a_real_url_legacy_cannot_encode(self) -> None:
        payload = compress_adaptive(LONG_TAIL_URL, ASCII_ALPHABET)
        self.assertTrue(is_v1_payload(payload, ASCII_ALPHABET))
        self.assertEqual(decompress_adaptive(payload, ASCII_ALPHABET), LONG_TAIL_URL)

    def test_v1_emoji_transport_is_prefix_safe(self) -> None:
        payload = compress_adaptive(LONG_TAIL_URL, EMOJI_ALPHABET)
        self.assertTrue(is_v1_payload(payload, EMOJI_ALPHABET))
        self.assertTrue(payload.startswith("〄"))
        self.assertGreater(payload_symbol_count(payload, EMOJI_ALPHABET), 1)
        self.assertEqual(decompress_adaptive(payload, EMOJI_ALPHABET), LONG_TAIL_URL)

    def test_cjk_transport_is_one_code_point_per_symbol_and_auto_detects(self) -> None:
        payload = compress_adaptive(LONG_TAIL_URL, CJK_ALPHABET)
        self.assertTrue(all(symbol in CJK_ALPHABET for symbol in payload))
        self.assertIs(infer_alphabet(payload), CJK_ALPHABET)
        self.assertEqual(decompress_adaptive(payload, CJK_ALPHABET), LONG_TAIL_URL)


class AdaptiveASGITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_cjk_api_output_round_trips_through_auto_decoder(self) -> None:
        compressed = self.client.post("/api/compress", json={"url": LONG_TAIL_URL, "mode": "cjk"})
        self.assertEqual(compressed.status_code, 200)
        payload = compressed.json()["payload"]
        self.assertTrue(all(symbol in CJK_ALPHABET for symbol in payload))
        decoded = self.client.post("/api/decompress", json={"payload": payload, "mode": "auto"})
        self.assertEqual(decoded.status_code, 200)
        self.assertEqual(decoded.json()["url"], LONG_TAIL_URL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
