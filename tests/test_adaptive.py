from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app import app
from ha_mr.diverse_phrases import inverse as diverse_phrase_inverse
from ha_mr.diverse_phrases import transform as diverse_phrase_transform
from ha_mr.general_phrases import inverse as general_phrase_inverse
from ha_mr.general_phrases import transform as general_phrase_transform
from ha_mr.host_transform import inverse as host_inverse
from ha_mr.host_transform import transform as host_transform
from ha_mr.semantic import inverse as semantic_inverse
from ha_mr.semantic import transform as semantic_transform

from ha_mr.codec import (
    ASCII_ALPHABET,
    CJK_ALPHABET,
    CJK_V2_ALPHABET,
    CJK_V2_MARKER,
    EMOJI_ALPHABET,
    adaptive_payload_version,
    compress,
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

    def test_semantic_transform_preserves_complex_url_bytes(self) -> None:
        url = (
            "https://example.com/redirect/12345678901234567890?next=https%3A%2F%2Fnews.example%2F"
            "a%20b&id=1ae03060-3f06-4a5c-9ac6-b5c1b4a62664&token=QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo"
        )
        transformed = semantic_transform(url.encode("utf-8"), opaque_tokens=True)
        self.assertLess(len(transformed), len(url.encode("utf-8")))
        self.assertEqual(semantic_inverse(transformed).decode("utf-8"), url)

    def test_frozen_host_transform_preserves_reddit_shared_link_shape(self) -> None:
        url = "https://www.reddit.com/r/python/comments/12345678901234567890/example?next=https%3A%2F%2Fexample.com%2Fdocs"
        transformed = host_transform(url.encode("utf-8"))
        self.assertLess(len(transformed), len(url.encode("utf-8")))
        self.assertEqual(host_inverse(transformed).decode("utf-8"), url)

    def test_historical_v5_direct_payload_remains_decodable(self) -> None:
        self.assertEqual(
            decompress_adaptive("oz~KA/;60*rw5", ASCII_ALPHABET),
            "https://www.youtube.com/watch?v=Xic_cDYrtnM",
        )

    def test_v19_compact_direct_frame_shrinks_and_round_trips_youtube_watch_url(self) -> None:
        url = "https://www.youtube.com/watch?v=Xic_cDYrtnM"
        legacy = compress(url, ASCII_ALPHABET)
        payload = compress_adaptive(url, ASCII_ALPHABET)
        self.assertEqual(adaptive_payload_version(payload, ASCII_ALPHABET), 19)
        self.assertLessEqual(payload_symbol_count(payload, ASCII_ALPHABET), 13)
        self.assertLess(payload_symbol_count(payload, ASCII_ALPHABET), payload_symbol_count(legacy, ASCII_ALPHABET))
        self.assertEqual(decompress_adaptive(payload, ASCII_ALPHABET), url)

    def test_frozen_general_phrase_transforms_round_trip(self) -> None:
        url = (
            "https://example.invalid/TranscribersOfReddit/wiki/format/images/guide?"
            "utm_source=mtgcardfetcher&search?q=general+phrase"
        ).encode("utf-8")
        general = general_phrase_transform(url)
        diverse = diverse_phrase_transform(url)
        self.assertEqual(general_phrase_inverse(general), url)
        self.assertEqual(diverse_phrase_inverse(diverse), url)
        self.assertTrue(general != url or diverse != url)

    def test_v17_compact_factorized_general_grammar_shrinks_and_round_trips(self) -> None:
        url = "https://www.reddit.com/r/AskReddit/wiki/index#rules"
        legacy = compress(url, ASCII_ALPHABET)
        payload = compress_adaptive(url, ASCII_ALPHABET)
        self.assertEqual(adaptive_payload_version(payload, ASCII_ALPHABET), 17)
        self.assertLess(payload_symbol_count(payload, ASCII_ALPHABET), payload_symbol_count(legacy, ASCII_ALPHABET))
        self.assertEqual(decompress_adaptive(payload, ASCII_ALPHABET), url)

    def test_v22_universal_prefix_frame_beats_older_opaque_candidates(self) -> None:
        url = (
            "https://example.com/redirect/12345678901234567890?next=https%3A%2F%2Fnews.example%2F"
            "a%20b&id=1ae03060-3f06-4a5c-9ac6-b5c1b4a62664&token=QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo"
        )
        payload = compress_adaptive(url, ASCII_ALPHABET)
        self.assertEqual(adaptive_payload_version(payload, ASCII_ALPHABET), 22)
        self.assertEqual(decompress_adaptive(payload, ASCII_ALPHABET), url)

    def test_v1_emoji_transport_is_prefix_safe(self) -> None:
        payload = compress_adaptive(LONG_TAIL_URL, EMOJI_ALPHABET)
        self.assertTrue(is_v1_payload(payload, EMOJI_ALPHABET))
        self.assertTrue(payload.startswith("〄"))
        self.assertGreater(payload_symbol_count(payload, EMOJI_ALPHABET), 1)
        self.assertEqual(decompress_adaptive(payload, EMOJI_ALPHABET), LONG_TAIL_URL)

    def test_historical_cjk_transport_remains_one_code_point_per_symbol_and_auto_detects(self) -> None:
        payload = compress_adaptive(LONG_TAIL_URL, CJK_ALPHABET)
        self.assertTrue(all(symbol in CJK_ALPHABET for symbol in payload))
        self.assertIs(infer_alphabet(payload), CJK_ALPHABET)
        self.assertEqual(decompress_adaptive(payload, CJK_V2_ALPHABET), LONG_TAIL_URL)

    def test_cjk_v2_transport_is_marked_and_beats_historical_radix(self) -> None:
        historical = compress_adaptive(LONG_TAIL_URL, CJK_ALPHABET)
        payload = compress_adaptive(LONG_TAIL_URL, CJK_V2_ALPHABET)
        self.assertTrue(payload.startswith(CJK_V2_MARKER))
        self.assertTrue(all(symbol in CJK_V2_ALPHABET for symbol in payload[1:]))
        self.assertIs(infer_alphabet(payload), CJK_V2_ALPHABET)
        self.assertLess(payload_symbol_count(payload, CJK_V2_ALPHABET), payload_symbol_count(historical, CJK_ALPHABET))
        self.assertEqual(decompress_adaptive(payload, CJK_V2_ALPHABET), LONG_TAIL_URL)


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
        self.assertTrue(payload.startswith(CJK_V2_MARKER))
        self.assertTrue(all(symbol in CJK_V2_ALPHABET for symbol in payload[1:]))
        decoded = self.client.post("/api/decompress", json={"payload": payload, "mode": "auto"})
        self.assertEqual(decoded.status_code, 200)
        self.assertEqual(decoded.json()["url"], LONG_TAIL_URL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
