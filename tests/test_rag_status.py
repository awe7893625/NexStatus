from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch

from nexstatus import local_integrations


class FakeResponse:
    def __init__(self, data: bytes | str):
        if isinstance(data, str):
            self._data = data.encode("utf-8")
        else:
            self._data = data

    def read(self, amt: int | None = None) -> bytes:
        if amt is not None and amt < len(self._data):
            return self._data[:amt]
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class FakeOpener:
    def __init__(self, responses: dict[str, FakeResponse | Exception]):
        self.responses = responses
        self.requested_urls: list[str] = []

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.requested_urls.append(url)
        if url in self.responses:
            resp = self.responses[url]
            if isinstance(resp, Exception):
                raise resp
            return resp
        raise urllib.error.URLError("Not found")


class TestRAGStatus(unittest.TestCase):
    def test_noredirecthandler_redirect_request(self):
        handler = local_integrations._NoRedirectHandler()
        res = handler.redirect_request(
            None, None, 302, "Found", {}, "http://example.com"
        )
        self.assertIsNone(res)

    def test_loopback_health_and_documents(self):
        health_body = json.dumps({"status": "ok"})
        docs_body = json.dumps(
            [
                "completed",
                "completed",
                "queued",
                "processing",
                "failed",
                {
                    "status": "completed",
                    "file_name": "secret.pdf",
                    "document_id": "doc123",
                },
                {"status": "unknown_status"},
            ]
        )

        fake_opener = FakeOpener(
            {
                "http://127.0.0.1:8220/api/health": FakeResponse(health_body),
                "http://127.0.0.1:8220/api/documents?latest_only=true": FakeResponse(
                    docs_body
                ),
            }
        )

        with patch("nexstatus.local_integrations._NO_REDIRECT_OPENER", fake_opener):
            res = local_integrations.rag_status("http://127.0.0.1:8220")

            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "online")
            self.assertEqual(res["inventory_status"], "live")

            # Document count check:
            # 2 string "completed" + 1 dict "completed" = 3
            # 1 string "queued" = 1
            # 1 string "processing" = 1
            # 1 string "failed" = 1
            # Total = 7
            self.assertEqual(res["documents"]["total"], 7)
            self.assertEqual(res["documents"]["completed"], 3)
            self.assertEqual(res["documents"]["queued"], 1)
            self.assertEqual(res["documents"]["processing"], 1)
            self.assertEqual(res["documents"]["failed"], 1)

            # Verification that file_name and document_id do NOT exist in the output dictionary
            res_str = json.dumps(res)
            self.assertNotIn("file_name", res_str)
            self.assertNotIn("document_id", res_str)
            self.assertNotIn("secret.pdf", res_str)
            self.assertNotIn("doc123", res_str)

    def test_invalid_urls_zero_requests(self):
        invalid_urls = [
            "https://127.0.0.1:8220",  # https not allowed
            "http://example.com:8220",  # non-loopback domain
            "http://user:pass@127.0.0.1:8220",  # userinfo
            "http://127.0.0.1:8220/path",  # path not allowed
            "http://127.0.0.1:8220?query=1",  # query not allowed
            "http://127.0.0.1:8220#fragment",  # fragment not allowed
            "http://127.0.0.1:abc",  # bad port
            "ftp://127.0.0.1:8220",  # ftp scheme
        ]

        fake_opener = FakeOpener({})
        with patch("nexstatus.local_integrations._NO_REDIRECT_OPENER", fake_opener):
            for url in invalid_urls:
                res = local_integrations.rag_status(url)
                self.assertFalse(res["ok"])
                self.assertEqual(res["status"], "invalid_config")
                self.assertEqual(res["error"], "rag_invalid_url")

            # Ensure zero requests were sent to opener
            self.assertEqual(len(fake_opener.requested_urls), 0)

    def test_health_error(self):
        fake_opener = FakeOpener(
            {
                "http://127.0.0.1:8220/api/health": urllib.error.URLError(
                    "Connection refused to http://secret-internal-host/path"
                ),
            }
        )

        with patch("nexstatus.local_integrations._NO_REDIRECT_OPENER", fake_opener):
            res = local_integrations.rag_status("http://127.0.0.1:8220")

            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "offline")
            self.assertEqual(res["error"], "rag_unavailable")

            res_str = json.dumps(res)
            self.assertNotIn("Connection refused", res_str)
            self.assertNotIn("secret-internal-host", res_str)
            self.assertNotIn("URLError", res_str)
            self.assertNotIn("Exception", res_str)

    def test_inventory_error_keeps_health_online(self):
        fake_opener = FakeOpener(
            {
                "http://127.0.0.1:8220/api/health": FakeResponse(
                    json.dumps({"status": "ok"})
                ),
                "http://127.0.0.1:8220/api/documents?latest_only=true": urllib.error.HTTPError(
                    "http://127.0.0.1:8220/api/documents",
                    500,
                    "Internal Error",
                    {},
                    None,
                ),
            }
        )

        with patch("nexstatus.local_integrations._NO_REDIRECT_OPENER", fake_opener):
            res = local_integrations.rag_status("http://127.0.0.1:8220")

            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "online")
            self.assertEqual(res["inventory_status"], "unavailable")
            self.assertEqual(
                res["documents"],
                {"total": 0, "completed": 0, "queued": 0, "processing": 0, "failed": 0},
            )


if __name__ == "__main__":
    unittest.main()
