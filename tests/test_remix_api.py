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


class TestUpdateTexturesBatch(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_empty_list(self):
        success, msg = self.client.update_textures_batch([])
        self.assertTrue(success)
        self.assertEqual(msg, "No textures to update")

    def test_successful_update(self):
        self.client.make_request = MagicMock(return_value={"success": True})
        textures = [
            {"material_prim": "/World/Mat", "texture_type": "diffuse", "texture_path": "/path/diffuse.dds"},
            {"material_prim": "/World/Mat", "texture_type": "normal", "texture_path": "/path/normal.dds"}
        ]

        success, msg = self.client.update_textures_batch(textures)

        self.assertTrue(success)
        self.assertIsNone(msg)

        self.client.make_request.assert_called_once()
        args, kwargs = self.client.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(args[1], "/stagecraft/material/textures/bulk")

        expected_payload = {
            "updates": [
                {"material_prim": "/World/Mat", "texture_type": "diffuse", "texture_path": "/path/diffuse.dds"},
                {"material_prim": "/World/Mat", "texture_type": "normal", "texture_path": "/path/normal.dds"}
            ]
        }
        self.assertEqual(kwargs["json_payload"], expected_payload)

    def test_batch_update_failure(self):
        self.client.make_request = MagicMock(return_value={"success": False, "error": "Internal Error"})
        textures = [
            {"material_prim": "/World/Mat", "texture_type": "diffuse", "texture_path": "/path/diffuse.dds"}
        ]

        success, msg = self.client.update_textures_batch(textures)

        self.assertFalse(success)
        self.assertEqual(msg, "Internal Error")

if __name__ == "__main__":
    unittest.main()
