"""Tests for remix_api.py — TLS policy and retry coverage."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject a mock requests module before importing remix_api so these tests run
# in environments where requests is not installed (e.g. minimal CI images).
# remix_api treats requests as optional and guards all usage behind _get_session().
_req_mock = MagicMock()
_RequestException = type("RequestException", (OSError,), {})
_ConnErr = type("ConnectionError", (_RequestException,), {})
_Timeout = type("Timeout", (_RequestException,), {})

_req_mock.exceptions.ConnectionError = _ConnErr
_req_mock.exceptions.Timeout = _Timeout
_req_mock.exceptions.RequestException = _RequestException
sys.modules.setdefault("requests", _req_mock)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from remix_api import RemixAPIClient  # noqa: E402


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


def _mock_session():
    """Return a mock session that make_request can call .request() on."""
    return MagicMock()


class TestTLSPolicy(unittest.TestCase):
    """make_request must apply verify=False for loopback and verify=True for remote."""

    def _capture_verify(self, base_url):
        client = _make_client(base_url)
        sess = _mock_session()
        sess.request.return_value = _mock_response()
        with patch.object(client, "_get_session", return_value=sess):
            client.make_request("GET", "/test", retries=1)
        _, kwargs = sess.request.call_args
        return kwargs.get("verify")

    def test_localhost_uses_verify_false(self):
        self.assertFalse(self._capture_verify("http://localhost:8011"))

    def test_127_uses_verify_false(self):
        self.assertFalse(self._capture_verify("http://127.0.0.1:8011"))

    def test_ipv6_loopback_uses_verify_false(self):
        self.assertFalse(self._capture_verify("http://[::1]:8011"))

    def test_remote_host_uses_verify_true(self):
        self.assertTrue(self._capture_verify("https://remix.example.com:8011"))

    def test_explicit_verify_true_overrides_localhost(self):
        client = _make_client("http://localhost:8011")
        sess = _mock_session()
        sess.request.return_value = _mock_response()
        with patch.object(client, "_get_session", return_value=sess):
            client.make_request("GET", "/test", retries=1, verify_ssl=True)
        _, kwargs = sess.request.call_args
        self.assertTrue(kwargs.get("verify"))


class TestRetryLogic(unittest.TestCase):
    def test_retries_on_connection_error(self):
        client = _make_client()
        sess = _mock_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            raise _ConnErr("refused")

        sess.request.side_effect = side_effect
        with patch.object(client, "_get_session", return_value=sess):
            with patch("time.sleep"):
                result = client.make_request("GET", "/test", retries=3)
        self.assertEqual(call_count[0], 3)
        self.assertFalse(result["success"])

    def test_no_retry_on_400(self):
        client = _make_client()
        sess = _mock_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            r = _mock_response(400)
            r.json.side_effect = ValueError
            return r

        sess.request.side_effect = side_effect
        with patch.object(client, "_get_session", return_value=sess):
            result = client.make_request("GET", "/test", retries=3)
        self.assertEqual(call_count[0], 1, "4xx must not retry")
        self.assertFalse(result["success"])

    def test_retries_on_429(self):
        client = _make_client()
        sess = _mock_session()
        call_count = [0]

        def side_effect(*a, **kw):
            call_count[0] += 1
            r = _mock_response(429)
            r.json.side_effect = ValueError
            return r

        sess.request.side_effect = side_effect
        with patch.object(client, "_get_session", return_value=sess):
            with patch("time.sleep"):
                result = client.make_request("GET", "/test", retries=3)
        self.assertGreater(call_count[0], 1, "429 should trigger retries")

    def test_success_on_first_attempt(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.return_value = _mock_response(200)
        with patch.object(client, "_get_session", return_value=sess):
            result = client.make_request("GET", "/test")
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)


class TestPing(unittest.TestCase):
    def test_ping_success(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.return_value = _mock_response(200)
        with patch.object(client, "_get_session", return_value=sess):
            ok, msg = client.ping()
        self.assertTrue(ok)
        # Verify ping targets the expected stagecraft project endpoint
        call_args = sess.request.call_args
        positional = call_args[0] if call_args[0] else ()
        url = positional[1] if len(positional) > 1 else call_args[1].get("url", "")
        self.assertIn("/stagecraft/project/", url)

    def test_ping_failure(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.side_effect = _ConnErr("refused")
        with patch.object(client, "_get_session", return_value=sess):
            ok, msg = client.ping()
        self.assertFalse(ok)


class TestGetMaterialTextures(unittest.TestCase):

    def test_missing_material_prim(self):
        client = _make_client()
        self.assertEqual(client.get_material_textures(None), {})
        self.assertEqual(client.get_material_textures(""), {})

    def test_success_with_valid_data(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {
                "success": True,
                "data": {"textures": {"albedo": "tex1.dds", "normal": "tex2.dds"}}
            }
            prim_path = "root/My Materials/Mat.usd"
            result = client.get_material_textures(prim_path)

            self.assertEqual(result, {"albedo": "tex1.dds", "normal": "tex2.dds"})

            mock_make_request.assert_called_once()
            called_method, called_url = mock_make_request.call_args[0]
            self.assertEqual(called_method, "GET")
            self.assertEqual(called_url, "/stagecraft/material/textures")
            self.assertEqual(mock_make_request.call_args[1].get("params"), {"material": prim_path})

    def test_api_failure(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {
                "success": False,
                "error": "API returned 404"
            }
            result = client.get_material_textures("mat")
            self.assertEqual(result, {})

    def test_success_but_missing_data(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {
                "success": True
                # data is missing
            }
            result = client.get_material_textures("mat")
            self.assertEqual(result, {})

    def test_success_but_invalid_data_format(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {
                "success": True,
                "data": None
            }
            result = client.get_material_textures("mat")
            self.assertEqual(result, {})

if __name__ == "__main__":
    unittest.main()
