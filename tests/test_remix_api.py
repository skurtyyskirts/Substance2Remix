"""Tests for remix_api.py — TLS policy and retry coverage."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from remix_api import RemixAPIClient


def _make_client(base_url="http://localhost:8011"):
    settings = {"api_base_url": base_url}
    return RemixAPIClient(settings_getter=lambda: settings, logger=MagicMock())


def _mock_response(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.text = "{}"
    r.json.return_value = body or {}
    return r


class TestTLSPolicy(unittest.TestCase):
    """make_request must apply verify=False for loopback and verify=True for remote."""

    def _capture_verify(self, base_url):
        client = _make_client(base_url)
        s = client._get_session()
        captured = {}
        mock_resp = _mock_response()
        with patch.object(s, "request", return_value=mock_resp) as m:
            client.make_request("GET", "/test", retries=1)
            _, kwargs = m.call_args
            captured["verify"] = kwargs.get("verify")
        return captured

    def test_localhost_uses_verify_false(self):
        result = self._capture_verify("http://localhost:8011")
        self.assertFalse(result["verify"])

    def test_127_uses_verify_false(self):
        result = self._capture_verify("http://127.0.0.1:8011")
        self.assertFalse(result["verify"])

    def test_remote_host_uses_verify_true(self):
        result = self._capture_verify("https://remix.example.com:8011")
        self.assertTrue(result["verify"])

    def test_explicit_verify_true_overrides_localhost(self):
        client = _make_client("http://localhost:8011")
        s = client._get_session()
        mock_resp = _mock_response()
        with patch.object(s, "request", return_value=mock_resp) as m:
            client.make_request("GET", "/test", retries=1, verify_ssl=True)
            _, kwargs = m.call_args
            self.assertTrue(kwargs.get("verify"))


class TestRetryLogic(unittest.TestCase):
    def test_retries_on_connection_error(self):
        import requests as req_lib
        client = _make_client()
        s = client._get_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            raise req_lib.exceptions.ConnectionError("refused")

        with patch.object(s, "request", side_effect=side_effect):
            with patch("time.sleep"):
                result = client.make_request("GET", "/test", retries=3)
        self.assertEqual(call_count[0], 3)
        self.assertFalse(result["success"])

    def test_no_retry_on_400(self):
        client = _make_client()
        s = client._get_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            r = _mock_response(400)
            r.json.side_effect = ValueError
            return r

        with patch.object(s, "request", side_effect=side_effect):
            result = client.make_request("GET", "/test", retries=3)
        self.assertEqual(call_count[0], 1, "4xx must not retry")
        self.assertFalse(result["success"])

    def test_retries_on_429(self):
        client = _make_client()
        s = client._get_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            r = _mock_response(429)
            r.json.side_effect = ValueError
            return r

        with patch.object(s, "request", side_effect=side_effect):
            with patch("time.sleep"):
                result = client.make_request("GET", "/test", retries=3)
        self.assertGreater(call_count[0], 1, "429 should trigger retries")

    def test_success_on_first_attempt(self):
        client = _make_client()
        s = client._get_session()
        with patch.object(s, "request", return_value=_mock_response(200)):
            result = client.make_request("GET", "/test")
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)


class TestPing(unittest.TestCase):
    def test_ping_success(self):
        client = _make_client()
        s = client._get_session()
        with patch.object(s, "request", return_value=_mock_response(200)):
            ok, msg = client.ping()
        self.assertTrue(ok)

    def test_ping_failure(self):
        import requests as req_lib
        client = _make_client()
        s = client._get_session()
        with patch.object(s, "request", side_effect=req_lib.exceptions.ConnectionError("refused")):
            ok, msg = client.ping()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
