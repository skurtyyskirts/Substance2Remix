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
_req_mock.exceptions.RequestException = _RequestException
_ConnErr = type("ConnectionError", (_RequestException,), {})
_Timeout = type("Timeout", (_RequestException,), {})
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


if __name__ == "__main__":
    unittest.main()

class TestIngestTexture(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    @patch("os.path.isfile")
    def test_file_not_found(self, mock_isfile):
        mock_isfile.return_value = False
        res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")
        self.assertIsNone(res)
        self.assertIn("File not found", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_api_request_failed(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        with patch.object(self.client, "make_request", return_value={"success": False, "error": "API Error"}):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNone(res)
        self.assertEqual(err, "API Error")

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_api_response_missing_path(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "completed_schemas": []
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNone(res)
        self.assertIn("Could not identify output path", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_happy_path_with_expected_suffix(self, mock_makedirs, mock_isfile):
        # We need isfile to be True for both the input file AND the output file check
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "content": ["path.a.rtex.dds", "path.n.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("path.a.rtex.dds") or res.endswith(os.path.join("path.a.rtex.dds")))
        self.assertIsNone(err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_fallback_match_when_suffix_missing(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "content": ["path.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("path.rtex.dds"))
        self.assertIsNone(err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_payload_construction(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        # We need to capture the payload sent to make_request
        mock_make_request = MagicMock(return_value={"success": False})

        with patch.object(self.client, "make_request", new=mock_make_request):
            self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        mock_make_request.assert_called_once()
        args, kwargs = mock_make_request.call_args

        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "/ingestcraft/mass-validator/queue/material")

        payload = kwargs.get("json_payload")
        self.assertIsNotNone(payload)

        # Verify ingest_type was mapped correctly (albedo -> DIFFUSE)
        input_files = payload["context_plugin"]["data"]["input_files"]
        self.assertEqual(len(input_files), 1)
        self.assertEqual(input_files[0][1], "DIFFUSE")


    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_completed_schemas_parsing(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "completed_schemas": [
                    {
                        "context_plugin": {
                            "data": {
                                "data_flows": [
                                    {
                                        "channel": "ingestion_output",
                                        "output_data": ["schema_path.a.rtex.dds"]
                                    }
                                ]
                            }
                        },
                        "check_plugins": []
                    }
                ]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/schema_path.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("schema_path.a.rtex.dds"))
        self.assertIsNone(err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_non_matching_file_skipped(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "content": ["wrong_name.a.rtex.dds", 123, "right_name.png", "right_name.n.rtex.dds", "right_name.a.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            # should pick right_name.a.rtex.dds because pbr_type is albedo
            res, err = self.client.ingest_texture("albedo", "/fake/right_name.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("right_name.a.rtex.dds"))
        self.assertIsNone(err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_missing_final_file(self, mock_makedirs, mock_isfile):
        # isfile is true for input, but false for the final output path
        mock_isfile.side_effect = [True, False]

        mock_response = {
            "success": True,
            "data": {
                "content": ["path.a.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNone(res)
        self.assertIn("File missing:", err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_fallback_match_when_expected_suffix_not_present(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "content": ["path.z.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("path.z.rtex.dds"))
        self.assertIsNone(err)

    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_no_expected_suffix(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True

        mock_response = {
            "success": True,
            "data": {
                "content": ["path.z.rtex.dds"]
            }
        }

        with patch.object(self.client, "make_request", return_value=mock_response):
            res, err = self.client.ingest_texture("unknown_type", "/fake/path.png", "/out")

        self.assertIsNotNone(res)
        self.assertTrue(res.endswith("path.z.rtex.dds"))
        self.assertIsNone(err)


    @patch("os.path.isfile")
    @patch("os.makedirs")
    def test_makedirs_exception(self, mock_makedirs, mock_isfile):
        mock_isfile.return_value = True
        mock_makedirs.side_effect = Exception("Permission denied")

        res, err = self.client.ingest_texture("albedo", "/fake/path.png", "/out")

        self.assertIsNone(res)
        self.assertIn("Failed to create directory", err)
