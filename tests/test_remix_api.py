"""Tests for remix_api.py — TLS policy and retry coverage."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Inject a mock requests module before importing remix_api so these tests run
# in environments where requests is not installed (e.g. minimal CI images).
# remix_api treats requests as optional and guards all usage behind _get_session().
_req_mock = MagicMock()
_ReqExc = type("RequestException", (OSError,), {})
_req_mock.exceptions.RequestException = _ReqExc
_ConnErr = type("ConnectionError", (_ReqExc,), {})
_Timeout = type("Timeout", (_ReqExc,), {})

_req_mock.exceptions.ConnectionError = _ConnErr
_req_mock.exceptions.Timeout = _Timeout

sys.modules.setdefault("requests", _req_mock)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from remix_api import RemixAPIClient  # noqa: E402


def _make_client(base_url="http://localhost:8011"):
    settings = {"api_base_url": base_url}
    return RemixAPIClient(settings_getter=lambda: settings, logger=MagicMock())


def _mock_response(status=200, body=None):
    if body and "success" not in body:
        body["success"] = status < 400
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




class TestIngestTexture(unittest.TestCase):
    def test_invalid_args(self):
        client = _make_client()
        ok, err = client.ingest_texture(None, "", "/out")
        self.assertFalse(ok)
        self.assertEqual(err, "Invalid arguments to ingest_texture")

    @patch("os.path.isfile")
    def test_file_not_found(self, mock_isfile):
        mock_isfile.return_value = False
        client = _make_client()
        res, err = client.ingest_texture("albedo", "missing.png", "/out")
        self.assertIsNone(res)
        self.assertIn("File not found", err)

    @patch("os.path.isfile")
    def test_api_request_fails(self, mock_isfile):
        mock_isfile.return_value = True
        client = _make_client()
        sess = _mock_session()
        # Mock failed response
        sess.request.return_value = _mock_response(500, {"success": False, "error": "Internal Server Error"})
        with patch.object(client, "_get_session", return_value=sess):
            with patch("os.makedirs"):
                res, err = client.ingest_texture("albedo", "test.png", "/out")
        self.assertIsNone(res)
        self.assertIn("Internal Server Error", err)

    @patch("os.path.isfile")
    def test_success_expected_suffix(self, mock_isfile):
        mock_isfile.return_value = True
        client = _make_client()
        sess = _mock_session()

        # Mock successful response with expected suffix 'a' for albedo
        api_response = {
            "completed_schemas": [
                    {
                        "context_plugin": {
                            "data": {
                                "data_flows": [
                                    {
                                        "channel": "ingestion_output",
                                        "output_data": ["test.a.rtex.dds", "test.n.rtex.dds"]
                                    }
                                ]
                            }
                        }
                    }
                ]
        }
        sess.request.return_value = _mock_response(200, api_response)

        with patch.object(client, "_get_session", return_value=sess):
            with patch("os.makedirs"):
                res, err = client.ingest_texture("albedo", "test.png", "/out")

        self.assertIsNotNone(res)
        self.assertIsNone(err)
        self.assertTrue(res.endswith("test.a.rtex.dds"))

    @patch("os.path.isfile")
    def test_success_fallback_suffix(self, mock_isfile):
        mock_isfile.return_value = True
        client = _make_client()
        sess = _mock_session()

        # Mock successful response without expected 'a' suffix, but base name matches
        api_response = {
            "completed_schemas": [
                    {
                        "context_plugin": {
                            "data": {
                                "data_flows": [
                                    {
                                        "channel": "ingestion_output",
                                        "output_data": ["test.x.rtex.dds"]
                                    }
                                ]
                            }
                        }
                    }
                ]
        }
        sess.request.return_value = _mock_response(200, api_response)

        with patch.object(client, "_get_session", return_value=sess):
            with patch("os.makedirs"):
                res, err = client.ingest_texture("albedo", "test.png", "/out")

        self.assertIsNotNone(res)
        self.assertIsNone(err)
        self.assertTrue(res.endswith("test.x.rtex.dds"))

    @patch("os.path.isfile")
    def test_file_missing_after_success(self, mock_isfile):
        # isfile returns True for the initial check, then False for final path check
        mock_isfile.side_effect = [True, False]
        client = _make_client()
        sess = _mock_session()

        api_response = {
            "completed_schemas": [
                    {
                        "context_plugin": {
                            "data": {
                                "data_flows": [
                                    {
                                        "channel": "ingestion_output",
                                        "output_data": ["test.a.rtex.dds"]
                                    }
                                ]
                            }
                        }
                    }
                ]
        }
        sess.request.return_value = _mock_response(200, api_response)

        with patch.object(client, "_get_session", return_value=sess):
            with patch("os.makedirs"):
                res, err = client.ingest_texture("albedo", "test.png", "/out")

        self.assertIsNone(res)
        self.assertIn("File missing", err)


if __name__ == "__main__":
    unittest.main()
