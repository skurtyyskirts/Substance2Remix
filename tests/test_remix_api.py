"""Tests for remix_api.py — TLS policy and retry coverage."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject a mock requests module before importing remix_api so these tests run
# in environments where requests is not installed (e.g. minimal CI images).
# remix_api treats requests as optional and guards all usage behind _get_session().
_req_mock = MagicMock()
class _RequestException(OSError): pass
class _ConnErr(_RequestException): pass
class _Timeout(_RequestException): pass
_req_mock.exceptions.RequestException = _RequestException
_req_mock.exceptions.ConnectionError = _ConnErr
_req_mock.exceptions.Timeout = _Timeout
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



class TestGetCurrentEditTarget(unittest.TestCase):
    def test_get_current_edit_target_success_layer(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {"success": True, "data": {"layer_id": "C:\\path\\to\\layer"}}

            result, err = client.get_current_edit_target()

            self.assertEqual(result, os.path.normpath("C:/path/to/layer"))
            self.assertIsNone(err)
            mock_make_request.assert_called_once_with('GET', "/stagecraft/layers/target")

    def test_get_current_edit_target_success_project_fallback(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            def make_request_side_effect(method, endpoint, **kwargs):
                if endpoint == "/stagecraft/layers/target":
                    return {"success": False, "data": None}
                elif endpoint == "/stagecraft/project/":
                    return {"success": True, "data": {"layer_id": "C:\\fallback\\path"}}
                return {"success": False}

            mock_make_request.side_effect = make_request_side_effect

            result, err = client.get_current_edit_target()

            self.assertEqual(result, os.path.normpath("C:/fallback/path"))
            self.assertIsNone(err)
            self.assertEqual(mock_make_request.call_count, 2)
            mock_make_request.assert_any_call('GET', "/stagecraft/layers/target")
            mock_make_request.assert_any_call('GET', "/stagecraft/project/")

    def test_get_current_edit_target_failure(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {"success": False, "data": None}

            result, err = client.get_current_edit_target()

            self.assertIsNone(result)
            self.assertEqual(err, "Could not determine edit layer.")
            self.assertEqual(mock_make_request.call_count, 2)

if __name__ == "__main__":
    unittest.main()

class TestGetMaterialFromMesh(unittest.TestCase):
    def test_empty_path(self):
        client = _make_client()
        result = client.get_material_from_mesh("")
        self.assertEqual(result, (None, "Mesh prim path cannot be empty."))

        result = client.get_material_from_mesh(None)
        self.assertEqual(result, (None, "Mesh prim path cannot be empty."))

    @patch.object(RemixAPIClient, "make_request")
    def test_success(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {
            "success": True,
            "data": {"asset_path": r"C:\material\path"}
        }

        result = client.get_material_from_mesh("/mesh/path")
        self.assertEqual(result, ("C:/material/path", None))

    @patch.object(RemixAPIClient, "make_request")
    def test_api_failure(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {
            "success": False,
            "error": "Some error"
        }

        result = client.get_material_from_mesh("/mesh/path")
        self.assertEqual(result, (None, "Some error"))

    @patch.object(RemixAPIClient, "make_request")
    def test_no_asset_path_in_data(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {
            "success": True,
            "data": {}
        }

        result = client.get_material_from_mesh("/mesh/path")
        self.assertEqual(result, (None, "Failed to query bound material."))

    @patch.object(RemixAPIClient, "make_request")
    def test_exception_handling(self, mock_make_request):
        client = _make_client()
        mock_make_request.side_effect = Exception("Some runtime error")

        result = client.get_material_from_mesh("/mesh/path")
        self.assertEqual(result, (None, "Some runtime error"))
