"""Tests for remix_api.py — request policy, Remix 1.6 REST shapes and ingest handling."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# The `requests` stub is installed by tests/conftest.py before this module
# loads. Pull the stubbed exception classes from there so raised errors match
# what remix_api will catch.
import requests as _req_mock  # actually the conftest stub
_ConnErr = _req_mock.exceptions.ConnectionError
_Timeout = _req_mock.exceptions.Timeout

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import remix_api  # noqa: E402
from remix_api import RemixAPIClient  # noqa: E402


def _make_client(base_url="http://localhost:8011", **extra):
    settings = {"api_base_url": base_url, **extra}
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

    def test_localhost_substring_spoof_uses_verify_true(self):
        # A hostile URL that merely *contains* "localhost" must NOT bypass TLS.
        self.assertTrue(self._capture_verify("https://localhost.evil.com:8011"))

    def test_127_substring_spoof_uses_verify_true(self):
        self.assertTrue(self._capture_verify("https://127.0.0.1.evil.com"))

    def test_uppercase_localhost_uses_verify_false(self):
        self.assertFalse(self._capture_verify("http://LOCALHOST:8011"))


class TestBaseUrlValidation(unittest.TestCase):
    """make_request must reject URLs that aren't http/https or lack a host."""

    def _call(self, base_url):
        client = _make_client(base_url)
        sess = _mock_session()
        sess.request.return_value = _mock_response()
        with patch.object(client, "_get_session", return_value=sess):
            return client.make_request("GET", "/test", retries=1), sess

    def test_file_scheme_rejected(self):
        result, sess = self._call("file:///etc/passwd")
        self.assertFalse(result["success"])
        self.assertIn("http or https", result["error"])
        sess.request.assert_not_called()

    def test_ftp_scheme_rejected(self):
        result, sess = self._call("ftp://remix.example.com")
        self.assertFalse(result["success"])
        sess.request.assert_not_called()

    def test_missing_host_rejected(self):
        result, sess = self._call("http://")
        self.assertFalse(result["success"])
        self.assertIn("hostname", result["error"])
        sess.request.assert_not_called()


class TestRetryLogic(unittest.TestCase):
    def _run(self, side_effect, retries=3):
        client = _make_client()
        sess = _mock_session()
        calls = [0]

        def wrapped(*a, **kw):
            calls[0] += 1
            return side_effect()

        sess.request.side_effect = wrapped
        with patch.object(client, "_get_session", return_value=sess):
            with patch("time.sleep"):
                result = client.make_request("GET", "/test", retries=retries)
        return result, calls[0]

    def test_connection_refused_fails_fast_with_clear_message(self):
        def refuse():
            raise _ConnErr("refused")
        result, calls = self._run(refuse)
        self.assertEqual(calls, 1, "a refused connection must not be retried")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("unreachable"))
        self.assertIn("Remix Toolkit running", result["error"])

    def test_timeouts_are_retried(self):
        def timeout():
            raise _Timeout("slow")
        result, calls = self._run(timeout)
        self.assertEqual(calls, 3)
        self.assertFalse(result["success"])

    def test_no_retry_on_400(self):
        def bad():
            r = _mock_response(400)
            r.json.side_effect = ValueError
            return r
        result, calls = self._run(bad)
        self.assertEqual(calls, 1, "4xx must not retry")
        self.assertFalse(result["success"])

    def test_retries_on_429(self):
        def throttled():
            r = _mock_response(429)
            r.json.side_effect = ValueError
            return r
        _, calls = self._run(throttled)
        self.assertGreater(calls, 1, "429 should trigger retries")

    def test_fastapi_detail_is_flattened(self):
        def unprocessable():
            return _mock_response(422, {"detail": [{"msg": "bad prim"}, {"msg": "bad path"}]})
        result, _ = self._run(unprocessable)
        self.assertIn("bad prim; bad path", result["error"])

    def test_success_on_first_attempt(self):
        result, calls = self._run(lambda: _mock_response(200))
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(calls, 1)

    def test_quiet_mode_logs_failures_at_debug(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.side_effect = _ConnErr("refused")
        with patch.object(client, "_get_session", return_value=sess):
            client.make_request("GET", "/test", log_failures=False)
        client.logger.warning.assert_not_called()


class TestProjectInfoAndPing(unittest.TestCase):
    def test_project_info_parses_layer(self):
        client = _make_client()
        with patch.object(client, "make_request", return_value={"success": True, "data": {"layer_id": "C:/Mods/MyMod/mod.usda"}}):
            info, err = client.get_project_info()
        self.assertIsNone(err)
        self.assertEqual(info["project_name"], "MyMod")
        self.assertEqual(info["project_file"], os.path.normpath("C:/Mods/MyMod/mod.usda"))

    def test_project_info_404_means_no_project(self):
        client = _make_client()
        with patch.object(client, "make_request", return_value={"success": False, "status_code": 404, "error": "x"}):
            info, err = client.get_project_info()
        self.assertIsNone(info)
        self.assertIn("no project is open", err)

    def test_ping_success(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.return_value = _mock_response(200, {"layer_id": "C:/Mods/MyMod/mod.usda"})
        with patch.object(client, "_get_session", return_value=sess):
            ok, msg = client.ping()
        self.assertTrue(ok)
        self.assertIn("MyMod", msg)
        url = sess.request.call_args[0][1]
        self.assertIn("/stagecraft/project/", url)

    def test_ping_failure(self):
        client = _make_client()
        sess = _mock_session()
        sess.request.side_effect = _ConnErr("refused")
        with patch.object(client, "_get_session", return_value=sess):
            ok, msg = client.ping()
        self.assertFalse(ok)


class TestPathHelpers(unittest.TestCase):
    def test_material_prim_from_material_and_shader(self):
        self.assertEqual(remix_api.material_prim_from_path("/RootNode/Looks/mat_ABCDEF0123456789"), "/RootNode/Looks/mat_ABCDEF0123456789")
        self.assertEqual(remix_api.material_prim_from_path("/RootNode/Looks/mat_ABCDEF0123456789/Shader"), "/RootNode/Looks/mat_ABCDEF0123456789")

    def test_material_prim_ignores_meshes_and_deep_children(self):
        self.assertIsNone(remix_api.material_prim_from_path("/RootNode/meshes/mesh_ABCDEF0123456789/mesh"))
        self.assertIsNone(remix_api.material_prim_from_path("/RootNode/Looks"))
        self.assertIsNone(remix_api.material_prim_from_path("/RootNode/Looks/mat_X/PreviewSurface"))

    def test_mesh_definition_from_instance_drops_index_suffix(self):
        # Mirrors REGEX_INSTANCE_TO_MESH_SUB in the Toolkit: inst_<HASH>_0 -> mesh_<HASH>.
        self.assertEqual(remix_api.mesh_definition_from_path("/RootNode/instances/inst_0123456789ABCDEF_0"), "/RootNode/meshes/mesh_0123456789ABCDEF")
        self.assertEqual(remix_api.mesh_definition_from_path("/RootNode/instances/inst_0123456789ABCDEF_12/ref_x/mesh"), "/RootNode/meshes/mesh_0123456789ABCDEF")
        self.assertEqual(remix_api.mesh_definition_from_path("/RootNode/meshes/mesh_0123456789ABCDEF/mesh"), "/RootNode/meshes/mesh_0123456789ABCDEF")
        self.assertIsNone(remix_api.mesh_definition_from_path("/RootNode/lights/light_0123456789ABCDEF"))

    def test_material_hash_and_ingest_types(self):
        self.assertEqual(remix_api.material_hash_from_prim("/RootNode/Looks/mat_DEADBEEFDEADBEEF"), "DEADBEEFDEADBEEF")
        self.assertIsNone(remix_api.material_hash_from_prim("/RootNode/Looks/Custom"))
        self.assertEqual(remix_api.ingest_type_for("normal", "opengl"), "NORMAL_OGL")
        self.assertEqual(remix_api.ingest_type_for("normal", "directx"), "NORMAL_DX")
        self.assertEqual(remix_api.ingest_type_for("albedo"), "DIFFUSE")
        # Only real Remix texture types: no OPACITY/AO (they 422 on ingest).
        self.assertNotIn("opacity", remix_api.PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP)
        self.assertNotIn("opacity", remix_api.PBR_TO_MDL_INPUT_MAP)


class TestGetSelection(unittest.TestCase):
    def test_extended_selection_is_split_and_deduplicated(self):
        client = _make_client()
        prims = [
            "/RootNode/instances/inst_0123456789ABCDEF_0",
            "/RootNode/meshes/mesh_0123456789ABCDEF",
            "/RootNode/meshes/mesh_0123456789ABCDEF/mesh",
            "/RootNode/Looks/mat_AAAABBBBCCCCDDDD",
            "/RootNode/Looks/mat_AAAABBBBCCCCDDDD/Shader",
            "/RootNode/instances/inst_FEDCBA9876543210_3",
        ]
        with patch.object(client, "make_request", return_value={"success": True, "data": {"prim_paths": prims}}) as req:
            sel, err = client.get_selection()
        self.assertIsNone(err)
        self.assertEqual(sel["materials"], ["/RootNode/Looks/mat_AAAABBBBCCCCDDDD"])
        self.assertEqual(sel["meshes"], ["/RootNode/meshes/mesh_0123456789ABCDEF", "/RootNode/meshes/mesh_FEDCBA9876543210"])
        self.assertEqual(req.call_args[1]["params"]["selection"], "true")

    def test_api_failure(self):
        client = _make_client()
        with patch.object(client, "make_request", return_value={"success": False, "error": "down"}):
            sel, err = client.get_selection()
        self.assertIsNone(sel)
        self.assertEqual(err, "down")

    def test_select_prims_keeps_leading_slash(self):
        client = _make_client()
        with patch.object(client, "make_request", return_value={"success": True}) as req:
            ok, err = client.select_prims(["/RootNode/Looks/mat_A", "/RootNode/Looks/mat_B"])
        self.assertTrue(ok)
        self.assertEqual(req.call_args[0][1], "/stagecraft/assets/selection//RootNode/Looks/mat_A,/RootNode/Looks/mat_B")


class TestResolveMeshFile(unittest.TestCase):
    def test_relative_reference_resolves_against_layer(self):
        client = _make_client()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "meshes"))
            mesh = os.path.join(tmp, "meshes", "mesh_0123456789ABCDEF.usd")
            open(mesh, "w").close()
            layer = os.path.join(tmp, "capture.usda").replace("\\", "/")
            data = {"reference_paths": [["/RootNode/meshes/mesh_0123456789ABCDEF", ["meshes/mesh_0123456789ABCDEF.usd", layer]]]}
            with patch.object(client, "make_request", return_value={"success": True, "data": data}) as req:
                path, err = client.resolve_mesh_file("/RootNode/meshes/mesh_0123456789ABCDEF")
        self.assertIsNone(err)
        self.assertEqual(os.path.normcase(path), os.path.normcase(os.path.normpath(mesh)))
        self.assertEqual(req.call_args[0][1], "/stagecraft/assets//RootNode/meshes/mesh_0123456789ABCDEF/file-paths")

    def test_absolute_reference_and_definition_fallback(self):
        client = _make_client()
        with tempfile.TemporaryDirectory() as tmp:
            mesh = os.path.join(tmp, "mesh.usd")
            open(mesh, "w").close()
            responses = [
                {"success": True, "data": {"reference_paths": []}},  # instance prim: no refs
                {"success": True, "data": {"reference_paths": [["/x", [mesh, os.path.join(tmp, "layer.usda")]]]}},
            ]
            with patch.object(client, "make_request", side_effect=responses) as req:
                path, err = client.resolve_mesh_file("/RootNode/instances/inst_0123456789ABCDEF_0")
        self.assertEqual(os.path.normcase(path), os.path.normcase(mesh))
        self.assertIn("/meshes/mesh_0123456789ABCDEF/file-paths", req.call_args_list[1][0][1])

    def test_missing_file_reports_error(self):
        client = _make_client()
        data = {"reference_paths": [["/x", ["C:/definitely/missing/mesh.usd", "C:/layer.usda"]]]}
        with patch.object(client, "make_request", return_value={"success": True, "data": data}):
            path, err = client.resolve_mesh_file("/RootNode/meshes/mesh_0123456789ABCDEF")
        self.assertIsNone(path)
        self.assertIn("not found", err)


class TestGetMaterialTextures(unittest.TestCase):
    @patch.object(RemixAPIClient, "make_request")
    def test_returns_textures_list(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {
            "success": True,
            "data": {"textures": [["albedo_texture", "/path/foo.dds"], ["normal_texture", "/path/bar.dds"]]},
        }
        textures, err = client.get_material_textures("/Looks/Mat")
        self.assertIsNone(err)
        self.assertEqual(len(textures), 2)
        self.assertEqual(textures[0][0], "albedo_texture")
        self.assertEqual(mock_make_request.call_args[0][1], "/stagecraft/assets//Looks/Mat/textures")

    @patch.object(RemixAPIClient, "make_request")
    def test_empty_data_returns_empty_list(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {"success": True, "data": {}}
        textures, err = client.get_material_textures("/Looks/Mat")
        self.assertIsNone(err)
        self.assertEqual(textures, [])

    @patch.object(RemixAPIClient, "make_request")
    def test_api_failure(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {"success": False, "error": "boom"}
        textures, err = client.get_material_textures("/Looks/Mat")
        self.assertIsNone(textures)
        self.assertEqual(err, "boom")

    def test_empty_prim_path(self):
        client = _make_client()
        textures, err = client.get_material_textures("")
        self.assertIsNone(textures)
        self.assertIn("missing", err.lower())


class TestUpdateTexturesBatch(unittest.TestCase):
    @patch.object(RemixAPIClient, "make_request")
    def test_empty_input_short_circuits(self, mock_make_request):
        client = _make_client()
        ok, msg = client.update_textures_batch([])
        self.assertTrue(ok)
        mock_make_request.assert_not_called()

    @patch.object(RemixAPIClient, "make_request")
    def test_relative_paths_rejected(self, mock_make_request):
        client = _make_client()
        ok, msg = client.update_textures_batch([("/Mat/Shader.inputs:diffuse_texture", "relative/path.dds")])
        self.assertFalse(ok)
        mock_make_request.assert_not_called()

    @patch.object(RemixAPIClient, "make_request")
    def test_absolute_paths_succeed_without_force(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {"success": True, "data": {}}
        abs_path = os.path.abspath("/foo/bar.rtex.dds")
        ok, msg = client.update_textures_batch([("/Mat/Shader.inputs:diffuse_texture", abs_path)])
        self.assertTrue(ok)
        method, endpoint = mock_make_request.call_args[0][:2]
        payload = mock_make_request.call_args[1].get("json_payload") or {}
        self.assertEqual(method, "PUT")
        self.assertEqual(endpoint, "/stagecraft/textures/")
        # Remix 1.6 rejects force=True without expected_current_textures.
        self.assertIs(payload.get("force"), False)
        self.assertNotIn("expected_current_textures", payload)
        self.assertEqual(len(payload.get("textures", [])), 1)
        self.assertNotIn("\\", payload["textures"][0][1])

    @patch.object(RemixAPIClient, "make_request")
    def test_api_failure_propagated(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {"success": False, "error": "remix said no"}
        ok, msg = client.update_textures_batch([
            ("/Mat/Shader.inputs:diffuse_texture", os.path.abspath("/foo/bar.dds")),
        ])
        self.assertFalse(ok)
        self.assertEqual(msg, "remix said no")

    @patch.object(RemixAPIClient, "make_request")
    def test_partial_success_returned_with_warnings(self, mock_make_request):
        client = _make_client()
        mock_make_request.return_value = {"success": True, "data": {}}
        ok, msg = client.update_textures_batch([
            ("/Mat/Shader.inputs:diffuse_texture", os.path.abspath("/foo/bar.dds")),
            ("/Mat/Shader.inputs:normal_texture", "relative.dds"),
        ])
        self.assertTrue(ok)
        self.assertIn("warning", msg.lower())


def _completed(outputs):
    return {"completed_schemas": [{
        "context_plugin": {"data": {"data_flows": [{"channel": "ingestion_output", "output_data": []}]}},
        "check_plugins": [{"data": {"data_flows": [{"channel": "ingestion_output", "output_data": outputs}]}}],
    }]}


class TestIngestTexture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "DEADBEEFDEADBEEF_Normal.png")
        open(self.src, "wb").close()
        self.out_dir = os.path.join(self.tmp.name, "remix_out")

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(RemixAPIClient, "make_request")
    def test_missing_file_short_circuits(self, mock_make_request):
        client = _make_client()
        result, err = client.ingest_texture("albedo", "/no/such/file.png", "/tmp/out")
        self.assertIsNone(result)
        self.assertIn("not found", err.lower())
        mock_make_request.assert_not_called()

    @patch.object(RemixAPIClient, "make_request")
    def test_missing_output_dir_short_circuits(self, mock_make_request):
        client = _make_client()
        result, err = client.ingest_texture("normal", self.src, None)
        self.assertIsNone(result)
        self.assertIn("output directory", err)
        mock_make_request.assert_not_called()

    def test_payload_keeps_default_pipeline_and_picks_octahedral_output(self):
        client = _make_client(remix_output_subfolder="Textures/Out", normal_map_format="opengl")
        ingest_dir = os.path.join(self.out_dir, "Textures", "Out")
        os.makedirs(ingest_dir)
        produced = os.path.join(ingest_dir, "DEADBEEFDEADBEEF_OTH_Normal.n.rtex.dds")
        open(produced, "wb").close()
        with patch.object(client, "make_request", return_value={"success": True, "data": _completed([produced])}) as req:
            result, err = client.ingest_texture("normal", self.src, self.out_dir)
        self.assertIsNone(err)
        self.assertEqual(os.path.normcase(result), os.path.normcase(produced))
        args, kwargs = req.call_args
        self.assertEqual(args[1], "/ingestcraft/mass-validator/queue/material")
        payload = kwargs["json_payload"]
        # Lists replace the server defaults wholesale: overriding check_plugins
        # would drop ConvertToOctahedral, so the payload must not carry it.
        self.assertNotIn("check_plugins", payload)
        self.assertNotIn("resultor_plugins", payload)
        data = payload["context_plugin"]["data"]
        self.assertEqual(data["input_files"][0][1], "NORMAL_OGL")
        self.assertTrue(data["output_directory"].endswith("Textures/Out"))
        self.assertEqual(kwargs["retries"], 1)


class TestPickIngestedOutput(unittest.TestCase):
    def test_prefers_expected_suffix_letter(self):
        outs = ["C:/o/H_Albedo.a.rtex.dds", "C:/o/H_Albedo.png"]
        self.assertEqual(remix_api._pick_ingested_output(outs, "C:/x/H_Albedo.png", "albedo"), "C:/o/H_Albedo.a.rtex.dds")

    def test_normal_with_lowercase_stem_gets_oth_suffix(self):
        outs = ["C:/o/H_normal_OTH_Normal.n.rtex.dds"]
        self.assertEqual(remix_api._pick_ingested_output(outs, "C:/x/H_normal.png", "normal"), outs[0])

    def test_unrelated_outputs_are_ignored_unless_alone(self):
        outs = ["C:/o/Other_Albedo.a.rtex.dds", "C:/o/Third.r.rtex.dds"]
        self.assertIsNone(remix_api._pick_ingested_output(outs, "C:/x/H_Albedo.png", "albedo"))
        self.assertEqual(remix_api._pick_ingested_output(outs[:1], "C:/x/H_Albedo.png", "albedo"), outs[0])

    def test_collects_outputs_from_completed_schemas(self):
        self.assertEqual(remix_api._collect_ingest_outputs(_completed(["a.dds"])), ["a.dds"])
        self.assertEqual(remix_api._collect_ingest_outputs({"content": ["b.dds"]}), ["b.dds"])
        self.assertEqual(remix_api._collect_ingest_outputs(None), [])


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

    def test_get_current_edit_target_failure(self):
        client = _make_client()
        with patch.object(client, "make_request") as mock_make_request:
            mock_make_request.return_value = {"success": False, "data": None}
            result, err = client.get_current_edit_target()
            self.assertIsNone(result)
            self.assertEqual(err, "Could not determine edit layer.")
            self.assertEqual(mock_make_request.call_count, 2)


class TestSaveLayer(unittest.TestCase):
    def test_missing_layer_id(self):
        client = _make_client()
        result, err = client.save_layer("")
        self.assertFalse(result)
        self.assertEqual(err, "Layer ID missing.")

        result, err = client.save_layer(None)
        self.assertFalse(result)
        self.assertEqual(err, "Layer ID missing.")

    @patch.object(RemixAPIClient, "get_current_edit_target")
    def test_verify_layer_fails(self, mock_get_target):
        client = _make_client()
        mock_get_target.return_value = (None, "Target error")
        result, err = client.save_layer("C:/dummy/layer.usda")
        self.assertFalse(result)
        self.assertEqual(err, "Could not verify layer: Target error")

    @patch.object(RemixAPIClient, "make_request")
    @patch.object(RemixAPIClient, "get_current_edit_target")
    def test_save_fails(self, mock_get_target, mock_make_request):
        client = _make_client()
        mock_get_target.return_value = ("C:/dummy/layer.usda", None)
        mock_make_request.return_value = {"success": False, "error": "Disk full"}
        result, err = client.save_layer("C:/dummy/layer.usda")
        self.assertFalse(result)
        self.assertEqual(err, "Disk full")

        mock_make_request.return_value = {"success": False}
        result, err = client.save_layer("C:/dummy/layer.usda")
        self.assertFalse(result)
        self.assertEqual(err, "Save failed.")

    @patch.object(RemixAPIClient, "make_request")
    @patch.object(RemixAPIClient, "get_current_edit_target")
    def test_save_success(self, mock_get_target, mock_make_request):
        client = _make_client()
        mock_get_target.return_value = ("C:/dummy/layer.usda", None)
        mock_make_request.return_value = {"success": True}
        result, err = client.save_layer("C:/dummy/layer.usda")
        self.assertTrue(result)
        self.assertIsNone(err)
        mock_make_request.assert_called_once_with('POST', '/stagecraft/layers/C:/dummy/layer.usda/save')


if __name__ == "__main__":
    unittest.main()
