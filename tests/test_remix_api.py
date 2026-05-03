"""Tests for remix_api.py — TLS policy and retry coverage."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject a mock requests module before importing remix_api so these tests run
# in environments where requests is not installed (e.g. minimal CI images).
# remix_api treats requests as optional and guards all usage behind _get_session().
_req_mock = MagicMock()
_ReqException = type("RequestException", (OSError,), {}); _ConnErr = type("ConnectionError", (_ReqException,), {})
_Timeout = type("Timeout", (_ReqException,), {})
_req_mock.exceptions.ConnectionError = _ConnErr
_req_mock.exceptions.Timeout = _Timeout
_req_mock.exceptions.RequestException = _ReqException
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


if __name__ == "__main__":
    unittest.main()

class TestIngestTexture(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_invalid_arguments(self):
        success, err = self.client.ingest_texture(None, "/fake/file.png", "/out")
        self.assertFalse(success)
        self.assertIn("Invalid arguments", err)

        success, err = self.client.ingest_texture("albedo", None, "/out")
        self.assertFalse(success)
        self.assertIn("Invalid arguments", err)

    @patch("os.path.isfile")
    def test_fallback_output_dir(self, mock_isfile):
        mock_isfile.return_value = False
        with patch.object(self.client, "get_project_default_output_dir", return_value="/default/out"):
            success, err = self.client.ingest_texture("albedo", "/fake/file.png", None)
            self.assertFalse(success)
            self.assertIn("File not found", err)

    @patch("os.path.isfile")
    def test_file_not_found(self, mock_isfile):
        mock_isfile.return_value = False
        success, err = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
        self.assertFalse(success)
        self.assertIn("File not found", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_mkdir_fails(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True
        mock_makedirs.side_effect = Exception("access denied")
        success, err = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
        self.assertFalse(success)
        self.assertIn("Failed to create directory", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_api_failure(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True
        mock_makedirs.return_value = None

        with patch.object(self.client, "make_request", return_value={"success": False, "error": "api down"}):
            success, err = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
            self.assertFalse(success)
            self.assertEqual(err, "api down")

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_success_completed_schemas(self, mock_makedirs, mock_isfile):
        # We need os.path.isfile to be True for the initial check, and True for the final check.
        # final check calls os.path.isfile(final_path)
        mock_isfile.return_value = True
        mock_makedirs.return_value = None

        api_resp = {
            "success": True,
            "data": {
                "completed_schemas": [
                    {
                        "check_plugins": [
                            {
                                "data": {
                                    "data_flows": [
                                        {"channel": "ingestion_output", "output_data": ["file.a.rtex.dds"]}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }
        with patch.object(self.client, "make_request", return_value=api_resp):
            # pbr_type "albedo" expects suffix "a"
            success, path = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
            self.assertTrue(success)
            self.assertTrue(path.endswith("file.a.rtex.dds"))

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_success_content_fallback(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True
        mock_makedirs.return_value = None

        api_resp = {
            "success": True,
            "data": {
                "content": ["file.n.rtex.dds"]
            }
        }
        with patch.object(self.client, "make_request", return_value=api_resp):
            # normal map -> expects suffix "n"
            success, path = self.client.ingest_texture("normal", "/fake/file.png", "/out")
            self.assertTrue(success)
            self.assertTrue(path.endswith("file.n.rtex.dds"))

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_output_path_not_identified(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True
        mock_makedirs.return_value = None

        # Missing paths entirely
        api_resp = {
            "success": True,
            "data": {}
        }
        with patch.object(self.client, "make_request", return_value=api_resp):
            success, err = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
            self.assertFalse(success)
            self.assertIn("Could not identify output path", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_file_missing_after_ingest(self, mock_makedirs, mock_isfile):
        # Return True for the initial check, False for the final check.
        # We can use side_effect with a list or a small function.
        def isfile_side_effect(p):
            # the initial file check
            if p == "/fake/file.png": return True
            # the final file check
            return False

        mock_isfile.side_effect = isfile_side_effect
        mock_makedirs.return_value = None

        api_resp = {
            "success": True,
            "data": {
                "content": ["file.a.rtex.dds"]
            }
        }
        with patch.object(self.client, "make_request", return_value=api_resp):
            success, err = self.client.ingest_texture("albedo", "/fake/file.png", "/out")
            self.assertFalse(success)
            self.assertIn("File missing", err)
