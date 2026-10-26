import os
import json
import time
import urllib.parse
import re
import ntpath
import threading

from .pbr_maps import PBR_MAPS, MAPS_BY_KEY, is_extended

# Attempt to import requests
try:
    import requests
except ImportError:
    requests = None

DEFAULT_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"
# The ingest endpoint can run for several minutes on large textures.
INGEST_REQUEST_TIMEOUT_SECONDS = 600.0

# Hostnames for which TLS verification is skipped by default (Remix exposes
# HTTP on the loopback interface). Compared against the parsed hostname, not
# a substring of the URL — otherwise a URL like https://localhost.evil.com
# would slip past loopback detection.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_local_host(url):
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in _LOCAL_HOSTS


def _validate_base_url(url):
    """Returns (parsed_url, error_message). error_message is None on success.

    Rejects URLs that aren't http/https or that lack a hostname so we never
    pass garbage like ``file://...`` or ``ftp://...`` to the requests layer.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return None, f"Invalid API base URL: {e}"
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None, f"API base URL must use http or https (got '{parsed.scheme}')."
    if not parsed.hostname:
        return None, "API base URL is missing a hostname."
    return parsed, None


# AperturePBR shader input name (without the "inputs:" prefix) -> plugin PBR type.
# Extra names cover materials authored with other shaders' input names.
REMIX_ATTR_SUFFIX_TO_PBR_MAP = {
    "albedo_texture": "albedo", "basecolor_texture": "albedo", "base_color_texture": "albedo",
    "normal_texture": "normal", "worldspacenormal_texture": "normal",
    "heightmap_texture": "height", "displacement_texture": "height",
    "roughness_texture": "roughness", "specularroughness_texture": "roughness",
    "metalness_texture": "metallic",
    "emissive_texture": "emissive", "emissive_color_texture": "emissive",
    **{m.remix_input: m.key for m in PBR_MAPS},
}

# Plugin PBR type -> AperturePBR shader input. Matches TEXTURE_TYPE_INPUT_MAP in
# the Remix Toolkit (omni.flux.asset_importer.core). AperturePBR has no opacity
# texture input: opacity is read from the albedo alpha channel.
PBR_TO_MDL_INPUT_MAP = {m.key: m.remix_input for m in PBR_MAPS}

# Plugin PBR type -> Remix ingest texture type (TextureTypeNames in the Toolkit).
# Normal maps are resolved per normal-map format by ingest_type_for().
PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP = {m.key: m.ingest_type for m in PBR_MAPS}

# Suffix Remix appends to converted textures (<stem>.<suffix>.rtex.dds).
_INGEST_SUFFIX_LETTER = {m.key: m.suffix for m in PBR_MAPS}

NORMAL_FORMAT_NAMES = {"opengl": "OpenGL", "directx": "DirectX"}

_HASH = r"[A-Za-z0-9]{16}"
# Instance/mesh prims: /RootNode/instances/inst_<HASH>_<N>[/...] or /RootNode/meshes/mesh_<HASH>[/...].
_MESH_PRIM_RE = re.compile(rf"^(?P<root>.*?)/(?:instances/inst_|meshes/mesh_)(?P<hash>{_HASH})(?:_\d+)*(?:/|$)")
_MESH_FILE_EXTENSIONS = ('.usd', '.usda', '.usdc', '.obj', '.fbx', '.gltf', '.glb')
_MATERIAL_PARENTS = ("Looks", "materials", "Material")


def ingest_type_for(pbr_type, normal_map_format="opengl"):
    """Remix ingest texture type for a plugin PBR type.

    For normal maps this is how Remix learns the convention: the ingest gives
    the material ``inputs:encoding`` 1 (OpenGL) or 2 (DirectX), and
    ConvertToOctahedral decodes the map with that convention.
    """
    pbr = str(pbr_type).lower()
    if pbr == "normal":
        return "NORMAL_DX" if str(normal_map_format).lower() == "directx" else "NORMAL_OGL"
    return PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP.get(pbr, "DIFFUSE")


def _extended_check_plugins(pbr_type):
    """check_plugins for a map that Remix's default "Material" pipeline drops.

    That pipeline's MaterialShaders step rebuilds the ingest material as
    AperturePBR from a fixed attribute list, which has no anisotropy or
    subsurface inputs, and its ConvertToDDS defaults don't list them either.
    The ingest stage is thrown away afterwards, so these maps skip the material
    conversion and get a ConvertToDDS entry for their input. The data flows
    match material_ingestion.json, so the output and its ingest metadata are
    written the same way as for the other maps.
    """
    m = MAPS_BY_KEY[pbr_type]
    block_format, gamma_encoded = m.dds
    return [{
        "name": "ConvertToDDS",
        "selector_plugins": [{"name": "AllShaders", "data": {}}],
        "resultor_plugins": [{"name": "FileCleanup", "data": {"channel": "cleanup_files", "cleanup_output": False}}],
        "data": {
            "conversion_settings": {
                f"inputs:{m.remix_input}": {"block_format": block_format, "gamma_encoded": gamma_encoded},
            },
            "data_flows": [
                {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "cleanup_files"},
                {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"},
                {"name": "InOutData", "push_output_data": True, "channel": "ingestion_output"},
            ],
        },
        "stop_if_fix_failed": True,
        "context_plugin": {"name": "CurrentStage", "data": {}},
    }]


def material_hash_from_prim(material_prim):
    """The 16-char capture hash at the end of a material prim path, or None."""
    m = re.search(rf"({_HASH})$", str(material_prim or ""))
    return m.group(1) if m else None


def material_prim_from_path(prim_path):
    """Return the material prim a selected path belongs to, or None.

    Accepts the material prim itself (.../Looks/mat_X) or its shader
    (.../Looks/mat_X/Shader). Deeper children of a material are ignored.
    """
    p = str(prim_path or "").replace('\\', '/').rstrip('/')
    if not p:
        return None
    if p.endswith("/Shader"):
        p = p[: -len("/Shader")]
    parts = p.split('/')
    if len(parts) >= 3 and parts[-2] in _MATERIAL_PARENTS and parts[-1] and "PreviewSurface" not in parts[-1]:
        return p
    return None


def mesh_definition_from_path(prim_path):
    """Map an instance or mesh prim (or any child of one) to its mesh definition.

    /RootNode/instances/inst_<HASH>_0/... -> /RootNode/meshes/mesh_<HASH>
    Mirrors REGEX_INSTANCE_TO_MESH_SUB in the Remix Toolkit, which drops the
    instance index suffix.
    """
    m = _MESH_PRIM_RE.match(str(prim_path or "").replace('\\', '/'))
    if not m:
        return None
    return f"{m.group('root')}/meshes/mesh_{m.group('hash')}"


class RemixAPIClient:
    def __init__(self, settings_getter, logger):
        """
        :param settings_getter: A callable that returns the current plugin settings dict.
        :param logger: An object or dict with debug, info, warning, error methods/keys.
        """
        self.settings_getter = settings_getter
        self.logger = logger
        self._session = None
        self._session_lock = threading.Lock()

    def _get_session(self):
        """
        Lazily create a thread-safe-ish requests.Session. requests.Session
        is mostly safe for concurrent use; we still guard creation with a
        lock to avoid two threads racing to instantiate.
        """
        if requests is None:
            return None
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    s = requests.Session()
                    # Bump pool size so concurrent ingest/update calls don't queue.
                    try:
                        from requests.adapters import HTTPAdapter
                        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
                        s.mount("http://", adapter)
                        s.mount("https://", adapter)
                    except Exception:
                        pass
                    self._session = s
        return self._session

    def close(self):
        """Release the underlying HTTP connection pool."""
        with self._session_lock:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

    def _log_debug(self, msg):
        if hasattr(self.logger, 'debug'): self.logger.debug(msg)
        elif isinstance(self.logger, dict) and 'debug' in self.logger: self.logger['debug'](msg)

    def _log_info(self, msg):
        if hasattr(self.logger, 'info'): self.logger.info(msg)
        elif isinstance(self.logger, dict) and 'info' in self.logger: self.logger['info'](msg)

    def _log_warning(self, msg):
        if hasattr(self.logger, 'warning'): self.logger.warning(msg)
        elif isinstance(self.logger, dict) and 'warning' in self.logger: self.logger['warning'](msg)

    def _log_error(self, msg, exc_info=False):
        if hasattr(self.logger, 'error'):
            try:
                self.logger.error(msg, exc_info=exc_info)
            except TypeError:
                self.logger.error(msg)
        elif isinstance(self.logger, dict) and 'error' in self.logger: self.logger['error'](msg)

    @staticmethod
    def safe_basename(path):
        if not path: return ""
        try: return ntpath.basename(str(path))
        except Exception: return str(path)

    def api_base_url(self):
        settings = self.settings_getter() or {}
        return str(settings.get("api_base_url", DEFAULT_REMIX_API_BASE_URL) or DEFAULT_REMIX_API_BASE_URL).rstrip('/')

    def make_request(self, method, url_endpoint, headers=None, json_payload=None, params=None, retries=3, delay=2, timeout=None, verify_ssl=None, log_failures=True):
        """
        Performs a Remix REST API request with retries and exponential backoff.

        :param verify_ssl: TLS verification behavior. None = default (True for
            non-localhost, False for localhost since RTX Remix exposes HTTP
            on 127.0.0.1 by default).
        :param log_failures: False demotes failure logging to DEBUG, for
            background polling that would otherwise fill the log while the
            Toolkit is closed.
        """
        if not requests:
            self._log_error("'requests' library is not available, network operations cannot proceed.")
            return {"success": False, "status_code": 0, "data": None, "error": "'requests' library not available."}

        settings = self.settings_getter() or {}
        effective_timeout = timeout if timeout is not None else settings.get("poll_timeout", DEFAULT_POLL_TIMEOUT_SECONDS)

        try:
            current_api_base = self.api_base_url()
        except Exception as e:
            self._log_error(f"URL construction error: {e}")
            return {"success": False, "status_code": 0, "data": None, "error": "URL construction error."}

        _, url_err = _validate_base_url(current_api_base)
        if url_err:
            self._log_error(url_err)
            return {"success": False, "status_code": 0, "data": None, "error": url_err}

        full_url = f"{current_api_base}/{url_endpoint.lstrip('/')}"

        # Default verify behavior: enabled for HTTPS to remote, disabled for
        # local-loopback HTTP (Remix's typical configuration). Hostname is
        # parsed via urlparse to avoid substring spoofing (localhost.evil.com).
        if verify_ssl is None:
            verify_ssl = not _is_local_host(current_api_base)

        base_headers = {'Accept': 'application/lightspeed.remix.service+json; version=1.0'}
        if json_payload is not None and 'Content-Type' not in (headers or {}):
            base_headers['Content-Type'] = 'application/lightspeed.remix.service+json; version=1.0'
        effective_headers = {**base_headers, **(headers or {})}

        self._log_debug(f"API Request: {method.upper()} {full_url}")

        return self._execute_request(
            method=method,
            full_url=full_url,
            effective_headers=effective_headers,
            json_payload=json_payload,
            params=params,
            effective_timeout=effective_timeout,
            verify_ssl=verify_ssl,
            retries=retries,
            delay=delay,
            log_failures=log_failures,
        )

    def _execute_request(self, method, full_url, effective_headers, json_payload, params, effective_timeout, verify_ssl, retries, delay, log_failures=True):
        """
        Executes the prepared request with retry logic.
        """
        last_error_message = "Request failed after multiple retries."
        session = self._get_session()
        log_failure = self._log_warning if log_failures else self._log_debug

        for attempt in range(1, retries + 1):
            try:
                if session is not None:
                    response = session.request(
                        method, full_url, headers=effective_headers, json=json_payload,
                        params=params, timeout=effective_timeout, verify=verify_ssl,
                    )
                else:
                    response = requests.request(
                        method, full_url, headers=effective_headers, json=json_payload,
                        params=params, timeout=effective_timeout, verify=verify_ssl,
                    )

                response_data = None
                try:
                    if response.content:
                        response_data = response.json()
                except (json.JSONDecodeError, ValueError):
                    pass

                if 200 <= response.status_code < 300:
                    return {
                        "success": True,
                        "status_code": response.status_code,
                        "data": response_data if response_data is not None else response.text,
                        "error": None,
                    }

                error_details = _error_detail(response_data) or response.text
                last_error_message = f"API Error (Status: {response.status_code}): {error_details}"
                log_failure(last_error_message)

                # 4xx errors won't get better with retry (except 408/429); fail fast.
                if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "data": response_data,
                        "error": last_error_message,
                    }

            except requests.exceptions.RequestException as e:
                # A refused (or never-accepted) connection means the Toolkit isn't
                # running or is on another port; retrying only delays the error.
                # ConnectTimeout is a ConnectionError; ReadTimeout (Remix accepted
                # but is still busy) is not, so it falls through to the retry path.
                if isinstance(e, requests.exceptions.ConnectionError):
                    log_failure(f"Connection failed: {e}")
                    return {
                        "success": False,
                        "status_code": 0,
                        "data": None,
                        "error": f"Can't reach RTX Remix at {self.api_base_url()}. Is the Remix Toolkit running with a project open?",
                        "unreachable": True,
                    }
                last_error_message = f"Request Exception: {e}"
                log_failure(f"Attempt {attempt} failed: {e}")

            if attempt < retries:
                # Exponential backoff with cap.
                sleep_s = min(float(delay) * (2 ** (attempt - 1)), 30.0)
                time.sleep(sleep_s)

        return {"success": False, "status_code": 0, "data": None, "error": last_error_message}

    # --- Project ---

    def get_project_info(self, timeout=None, log_failures=True):
        """Return ({"project_file", "project_dir", "project_name"}, error).

        Remix answers 404 when the Toolkit is running without a loaded project;
        that case is reported as an error so callers can stop early.
        """
        res = self.make_request('GET', "/stagecraft/project/", retries=1, delay=0, timeout=timeout, log_failures=log_failures)
        if not res.get("success"):
            if res.get("status_code") == 404:
                return None, "RTX Remix is running but no project is open."
            return None, res.get("error") or "Failed to query the Remix project."
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        layer_id = data.get("layer_id")
        if not isinstance(layer_id, str) or not layer_id.strip():
            return None, "RTX Remix returned no project path."
        project_file = os.path.normpath(layer_id)
        project_dir = os.path.dirname(project_file)
        return {
            "project_file": project_file,
            "project_dir": project_dir,
            "project_name": os.path.basename(project_dir) or os.path.splitext(os.path.basename(project_file))[0],
        }, None

    def ping(self, timeout=2.0, log_failures=True):
        """
        Fast health check for the Remix API endpoint.
        Uses a short timeout and a single attempt to keep UI responsive.
        Returns (ok, message); ok is True only when a project is loaded.
        """
        info, err = self.get_project_info(timeout=timeout, log_failures=log_failures)
        if info:
            return True, f"Connected - {info['project_name']}"
        return False, err or "Connection failed"

    def get_project_default_output_dir(self):
        self._log_debug("Getting Remix project default output directory...")
        result = self.make_request('GET', "/stagecraft/assets/default-directory")

        if result["success"] and isinstance(result.get("data"), dict):
            default_dir_raw = result["data"].get("directory_path") or result["data"].get("asset_path")
            if isinstance(default_dir_raw, str):
                try:
                    default_dir_abs = os.path.abspath(os.path.normpath(default_dir_raw))
                    return default_dir_abs, None
                except Exception as e:
                    return None, f"Error processing path: {e}"
            else:
                return None, "API success but expected directory path missing."
        return None, result['error'] or "Failed to get default directory from Remix API."

    def derive_project_name_from_dir(self, remix_dir_path):
        if not remix_dir_path: return "UnknownProject"
        try:
            path_norm = os.path.abspath(os.path.normpath(remix_dir_path))
            parts = []
            cursor = path_norm
            for _ in range(6):
                base = os.path.basename(cursor)
                if base: parts.append(base)
                parent = os.path.dirname(cursor)
                if parent == cursor: break
                cursor = parent

            known_tail_names = {"textures", "painterconnector_ingested", "ingested", "captures", "assets", "output", "export"}
            for name in parts:
                if name.lower() not in known_tail_names and name:
                    return name
        except Exception:
            pass
        return "UnknownProject"

    # --- Selection ---

    def get_selection(self):
        """Read the Remix viewport selection.

        Remix returns the *extended* selection: a selected instance also brings
        its mesh, bound material and shader (prim_utils.get_extended_selection).
        Returns ({"materials": [...], "meshes": [...], "prims": [...]}, error).
        Materials and mesh definitions are de-duplicated and sorted so the
        result is stable (the server builds the list from a set).
        """
        result = self.make_request('GET', "/stagecraft/assets/", params={"selection": "true", "filter_session_prims": "false"})
        if not result.get("success"):
            return None, result.get("error") or "Failed to read the Remix selection."

        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        prims = [p.replace('\\', '/') for p in (data.get("prim_paths") or data.get("asset_paths") or []) if isinstance(p, str) and p]

        materials, meshes = set(), set()
        for p in prims:
            mat = material_prim_from_path(p)
            if mat:
                materials.add(mat)
                continue
            mesh = mesh_definition_from_path(p)
            if mesh:
                meshes.add(mesh)

        return {"materials": sorted(materials), "meshes": sorted(meshes), "prims": sorted(set(prims))}, None

    def select_prims(self, prim_paths):
        """Replace the Remix viewport selection with the given prims."""
        paths = [str(p).replace('\\', '/') for p in (prim_paths or []) if p]
        if not paths:
            return False, "Nothing to select."
        # Prim paths keep their leading "/" (hence the double slash): Remix
        # validates the raw path parameter against the USD stage.
        encoded = urllib.parse.quote(",".join(paths), safe="/,")
        res = self.make_request('PUT', f"/stagecraft/assets/selection/{encoded}", retries=1)
        if res.get("success"):
            return True, None
        return False, res.get("error") or "Failed to set the Remix selection."

    def resolve_mesh_file(self, prim_path):
        """Return (absolute mesh file path, error) for a mesh or instance prim.

        Queries the prim's USD references (``/file-paths``). Each entry is
        ``[prim, [reference_path, layer_path]]``; relative references resolve
        against the directory of the layer that authored them. The bare mesh
        definition is tried as a fallback because instance sub-prims usually
        carry no references of their own.
        """
        if not prim_path: return None, "Prim path empty."
        prim_norm = str(prim_path).replace('\\', '/')
        attempts = [prim_norm]
        definition = mesh_definition_from_path(prim_norm)
        if definition and definition != prim_norm:
            attempts.append(definition)

        last_err = "No mesh reference found."
        for query_path in attempts:
            encoded = urllib.parse.quote(query_path, safe='/')
            res = self.make_request('GET', f"/stagecraft/assets/{encoded}/file-paths", retries=1)
            if not res.get("success"):
                last_err = res.get("error") or last_err
                continue
            data = res.get("data") if isinstance(res.get("data"), dict) else {}
            for entry in data.get("reference_paths") or []:
                ref, layer = _split_reference_entry(entry)
                if not ref or not ref.lower().endswith(_MESH_FILE_EXTENSIONS):
                    continue
                if not os.path.isabs(ref):
                    if not layer or not os.path.isabs(layer):
                        last_err = f"Relative mesh reference without a layer: {ref}"
                        continue
                    ref = os.path.join(os.path.dirname(layer), ref)
                path = os.path.normpath(ref)
                if os.path.isfile(path):
                    return path, None
                last_err = f"Mesh file not found on disk: {path}"
        return None, last_err

    # --- Materials / textures ---

    def get_material_textures(self, material_prim):
        if not material_prim: return None, "Material prim missing."
        encoded = urllib.parse.quote(str(material_prim).replace(os.sep, "/"), safe="/")
        res = self.make_request("GET", f"/stagecraft/assets/{encoded}/textures")
        if res.get("success") and isinstance(res.get("data"), dict):
            return res["data"].get("textures", []), None
        return None, res.get("error", "Failed to get textures.")

    def ingest_texture(self, pbr_type, texture_file_path, project_output_dir_abs, normal_map_format=None, output_subfolder=None):
        """Ingest one texture through the Remix "Material" ingestion schema.

        Only the TextureImporter context data is overridden. The Toolkit merges
        dicts recursively but replaces lists wholesale, so leaving check_plugins
        alone keeps its default pipeline: MaterialShaders -> ConvertToOctahedral
        -> ConvertToDDS. Normal maps must go through ConvertToOctahedral, since
        AperturePBR materials default to octahedral normal encoding. Maps that
        pipeline drops (anisotropy, subsurface) send their own check_plugins.

        ``normal_map_format`` and ``output_subfolder`` default to the settings;
        a push passes the values it exported with so a settings change made
        while it runs can't mislabel the normal map.
        """
        if not os.path.isfile(texture_file_path):
            return None, f"File not found: {texture_file_path}"
        if not project_output_dir_abs:
            return None, "Remix project output directory is unknown."

        settings = self.settings_getter() or {}
        if output_subfolder is None:
            output_subfolder = settings.get("remix_output_subfolder", "Textures/PainterConnector_Ingested")
        if normal_map_format is None:
            normal_map_format = settings.get("normal_map_format", "opengl")
        target_ingest_dir_abs = os.path.normpath(os.path.join(project_output_dir_abs, str(output_subfolder).strip('/\\')))

        try: os.makedirs(target_ingest_dir_abs, exist_ok=True)
        except Exception as e: return None, f"Failed to create directory: {e}"

        abs_texture_path = os.path.abspath(texture_file_path).replace(os.sep, '/')
        target_ingest_dir_api = os.path.abspath(target_ingest_dir_abs).replace(os.sep, '/')
        ingest_type = ingest_type_for(pbr_type, normal_map_format)
        self._log_info(f"Ingesting {pbr_type} as {ingest_type}: {self.safe_basename(texture_file_path)}")

        ingest_payload = {
            "executor": 1,
            "name": f"Ingest_{pbr_type}_{self.safe_basename(abs_texture_path)}",
            "context_plugin": {
                "name": "TextureImporter",
                "data": {
                    # A dedicated USD context so we never clobber the stage of an
                    # open IngestCraft tab.
                    "context_name": "ingestcraft_browser",
                    "input_files": [[abs_texture_path, ingest_type]],
                    "output_directory": target_ingest_dir_api,
                    "allow_empty_input_files_list": True,
                    "hide_context_ui": True,
                    "create_context_if_not_exist": True,
                    "expose_mass_ui": False,
                    "cook_mass_template": True,
                },
            },
        }
        if is_extended(pbr_type):
            ingest_payload["check_plugins"] = _extended_check_plugins(pbr_type)
            # The schema's shared "max conversions" control targets ConvertToOctahedral,
            # which these maps don't run; Remix rejects a target that's missing.
            ingest_payload["data"] = {"mass_ui": {"shared_int_fields": []}}

        # Ingest is long-running; use a much larger timeout and no retries
        # so we don't accidentally re-queue a job the server is still working on.
        res = self.make_request(
            "POST",
            "/ingestcraft/mass-validator/queue/material",
            json_payload=ingest_payload,
            retries=1,
            timeout=INGEST_REQUEST_TIMEOUT_SECONDS,
        )
        if not res["success"]: return None, res.get("error")

        output_paths = _collect_ingest_outputs(res.get("data"))
        ingested_path = _pick_ingested_output(output_paths, abs_texture_path, pbr_type)
        if not ingested_path:
            self._log_debug(f"Ingest outputs for {self.safe_basename(abs_texture_path)}: {output_paths}")
            return None, "Could not identify output path from API response."

        final_path = os.path.normpath(ingested_path) if os.path.isabs(ingested_path) else os.path.normpath(os.path.join(target_ingest_dir_abs, ingested_path))
        if not os.path.isfile(final_path): return None, f"File missing: {final_path}"

        return final_path, None

    def get_current_edit_target(self):
        self._log_debug("Getting current edit target layer from Remix...")
        result = self.make_request('GET', "/stagecraft/layers/target")
        layer_id = result.get("data", {}).get("layer_id") if result["success"] and isinstance(result.get("data"), dict) else None

        if not layer_id:
            result_proj = self.make_request('GET', "/stagecraft/project/")
            layer_id = result_proj.get("data", {}).get("layer_id") if result_proj["success"] and isinstance(result_proj.get("data"), dict) else None

        if isinstance(layer_id, str) and layer_id.strip():
            return os.path.normpath(layer_id.replace('\\', '/')), None

        return None, "Could not determine edit layer."

    def save_layer(self, layer_id_abs_path=None):
        """Save the current edit target layer.

        ``layer_id_abs_path`` is only a precondition: the edit target is
        re-read so we always save the layer Remix actually authored into.
        """
        if not layer_id_abs_path: return False, "Layer ID missing."

        current_layer, err = self.get_current_edit_target()
        if err or not current_layer: return False, f"Could not verify layer: {err}"

        encoded = urllib.parse.quote(current_layer.replace(os.sep, '/'), safe=':/')
        result = self.make_request('POST', f"/stagecraft/layers/{encoded}/save")

        if result["success"]: return True, None
        return False, result.get("error", "Save failed.")

    def update_textures_batch(self, textures_to_update):
        """Point material inputs at freshly ingested textures.

        Sent with force=False: Remix then requires each file to be a validated
        ingest output, which ingest_texture() guarantees. (Remix 1.6 rejects
        force=True unless the exact current values are also supplied.)
        """
        if not textures_to_update: return True, "No textures."

        payload_list = []
        path_errors = []
        for usd_attr, ingested_path in textures_to_update:
            if not ingested_path or not os.path.isabs(ingested_path):
                path_errors.append(f"Path not absolute: {usd_attr}")
                continue
            payload_list.append([usd_attr.replace('\\', '/'), ingested_path.replace(os.sep, '/')])

        if not payload_list: return False, "No valid paths."

        payload = {"force": False, "textures": payload_list}
        result = self.make_request('PUT', '/stagecraft/textures/', json_payload=payload)

        if not result["success"]:
            return False, result.get("error", "Batch update failed.")

        if path_errors:
            return True, f"Success with warnings: {path_errors}"
        return True, None


def _error_detail(response_data):
    """Flatten a FastAPI error body ({"detail": ...}) into readable text."""
    if not response_data:
        return None
    if isinstance(response_data, dict) and "detail" in response_data:
        detail = response_data["detail"]
        if isinstance(detail, list):
            msgs = [str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail]
            return "; ".join(msgs)
        return str(detail)
    return str(response_data)


def _split_reference_entry(entry):
    """Normalize one ``reference_paths`` entry to (reference, layer)."""
    ref, layer = None, None
    if isinstance(entry, (list, tuple)):
        if len(entry) == 2 and isinstance(entry[1], (list, tuple)):
            pair = list(entry[1])
            ref = pair[0] if pair else None
            layer = pair[1] if len(pair) > 1 else None
        elif entry:
            ref = entry[0]
            layer = entry[1] if len(entry) > 1 else None
    elif isinstance(entry, str):
        ref = entry
    ref = ref.replace('\\', '/') if isinstance(ref, str) and ref else None
    layer = layer.replace('\\', '/') if isinstance(layer, str) and layer else None
    return ref, layer


def _collect_ingest_outputs(data):
    """Every path pushed on the "ingestion_output" channel of a completed ingest."""
    output_paths = []
    data = data if isinstance(data, dict) else {}
    for schema in data.get("completed_schemas") or []:
        if not isinstance(schema, dict):
            continue
        plugin_results = [schema.get("context_plugin") or {}] + list(schema.get("check_plugins") or [])
        for pr in plugin_results:
            pr_data = pr.get("data") if isinstance(pr, dict) else None
            for flow in (pr_data or {}).get("data_flows") or []:
                if isinstance(flow, dict) and flow.get("channel") == "ingestion_output":
                    output_paths.extend(p for p in flow.get("output_data") or [] if isinstance(p, str))
    if not output_paths and isinstance(data.get("content"), list):
        output_paths.extend(p for p in data["content"] if isinstance(p, str))
    return output_paths


def _ingest_output_stem(dds_path):
    """'foo_OTH_Normal.n.rtex.dds' -> ('foo_OTH_Normal', 'n')."""
    base = ntpath.basename(str(dds_path))
    lower = base.lower()
    for ext in (".rtex.dds", ".dds"):
        if lower.endswith(ext):
            base = base[: -len(ext)]
            break
    m = re.match(r"^(.*)\.([a-z]{1,2})$", base, flags=re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower()
    return base, None


def _pick_ingested_output(output_paths, input_path, pbr_type):
    """Choose the converted DDS that belongs to ``input_path``.

    Remix names outputs ``<stem>.<letter>.rtex.dds``. Normal maps are renamed
    by the octahedral conversion first (``X_Normal`` -> ``X_OTH_Normal``, any
    other stem -> ``<stem>_OTH_Normal``), so a stem that merely starts with the
    input stem also counts.
    """
    input_stem = os.path.splitext(ntpath.basename(str(input_path)))[0]
    if input_stem.lower().endswith(".rtex"):
        input_stem = input_stem[: -len(".rtex")]
    input_l = input_stem.lower()
    accepted = {input_l}
    if input_l.endswith("_normal"):
        accepted.add(input_l[: -len("_normal")] + "_oth_normal")
    expected_letter = _INGEST_SUFFIX_LETTER.get(str(pbr_type).lower())

    exact, loose = [], []
    for p in output_paths:
        if not str(p).lower().endswith(".dds"):
            continue
        stem, letter = _ingest_output_stem(p)
        stem_l = stem.lower()
        if stem_l in accepted or stem_l.startswith(input_l + "_oth"):
            (exact if letter == expected_letter else loose).append(p)
    if exact:
        return exact[0]
    if loose:
        return loose[0]
    dds = [p for p in output_paths if str(p).lower().endswith(".dds")]
    # One texture per request: a lone DDS can only be ours.
    return dds[0] if len(dds) == 1 else None
