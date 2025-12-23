import os
import sys
import json
import time
import urllib.parse
import re
import ntpath

# Attempt to import requests
try:
    import requests
except ImportError:
    requests = None

DEFAULT_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"

REMIX_ATTR_SUFFIX_TO_PBR_MAP = {
    "diffuse_texture": "albedo", "albedo_texture": "albedo", "basecolor_texture": "albedo", "base_color_texture": "albedo",
    "normalmap_texture": "normal", "normal_texture": "normal", "worldspacenormal_texture": "normal",
    "heightmap_texture": "height", "height_texture": "height", "displacement_texture": "height",
    "roughness_texture": "roughness", "reflectionroughness_texture": "roughness", "specularroughness_texture": "roughness",
    "metallic_texture": "metallic", "metalness_texture": "metallic",
    "emissive_mask_texture": "emissive", "emissive_texture": "emissive", "emissive_color_texture": "emissive",
    "opacity_texture": "opacity", "opacitymask_texture": "opacity", "opacity": "opacity", "transparency_texture": "opacity",
}

PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP = {
    "albedo": "DIFFUSE", "normal": "NORMAL_DX", "height": "HEIGHT",
    "roughness": "ROUGHNESS", "metallic": "METALLIC", "emissive": "EMISSIVE",
    "ao": "AO", "opacity": "OPACITY",
}

class RemixAPIClient:
    def __init__(self, settings_getter, logger):
        """
        :param settings_getter: A callable that returns the current plugin settings dict.
        :param logger: An object or dict with debug, info, warning, error methods/keys.
        """
        self.settings_getter = settings_getter
        self.logger = logger

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

    def make_request(self, method, url_endpoint, headers=None, json_payload=None, params=None, retries=3, delay=2, timeout=None, verify_ssl=False):
        if not requests:
            self._log_error("'requests' library is not available, network operations cannot proceed.")
            return {"success": False, "status_code": 0, "data": None, "error": "'requests' library not available."}

        settings = self.settings_getter()
        effective_timeout = timeout if timeout is not None else settings.get("poll_timeout", DEFAULT_POLL_TIMEOUT_SECONDS)
        
        try:
            current_api_base = settings.get("api_base_url", DEFAULT_REMIX_API_BASE_URL).rstrip('/')
            full_url = f"{current_api_base}/{url_endpoint.lstrip('/')}"
        except Exception as e:
            self._log_error(f"URL construction error: {e}")
            return {"success": False, "status_code": 0, "data": None, "error": "URL construction error."}

        base_headers = {'Accept': 'application/lightspeed.remix.service+json; version=1.0'}
        if json_payload is not None and 'Content-Type' not in (headers or {}):
            base_headers['Content-Type'] = 'application/lightspeed.remix.service+json; version=1.0'
        effective_headers = {**base_headers, **(headers or {})}

        self._log_debug(f"API Request: {method.upper()} {full_url}")
        
        last_error_message = "Request failed after multiple retries."

        for attempt in range(1, retries + 1):
            try:
                response = requests.request(method, full_url, headers=effective_headers, json=json_payload, params=params, timeout=effective_timeout, verify=verify_ssl)
                response_data = None
                try:
                    if response.content: response_data = response.json()
                except json.JSONDecodeError:
                    pass

                if 200 <= response.status_code < 300:
                    return {"success": True, "status_code": response.status_code, "data": response_data if response_data is not None else response.text, "error": None}
                else:
                    error_details = response_data or response.text
                    last_error_message = f"API Error (Status: {response.status_code}): {error_details}"
                    self._log_warning(last_error_message)
                    
            except requests.exceptions.RequestException as e:
                last_error_message = f"Request Exception: {e}"
                self._log_warning(f"Attempt {attempt} failed: {e}")
            
            if attempt < retries:
                time.sleep(delay)

        return {"success": False, "status_code": 0, "data": None, "error": last_error_message}

    def get_project_default_output_dir(self):
        self._log_info("Getting Remix project default output directory...")
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

    def get_material_from_mesh(self, mesh_prim_path):
        if not mesh_prim_path: return None, "Mesh prim path cannot be empty."
        try:
            encoded_mesh_path = urllib.parse.quote(mesh_prim_path.replace(os.sep, '/'), safe='/')
            result = self.make_request('GET', f"/stagecraft/assets/{encoded_mesh_path}/material")
            if result["success"] and isinstance(result.get("data"), dict):
                material_path_raw = result["data"].get("asset_path")
                if isinstance(material_path_raw, str):
                    return material_path_raw.replace('\\', '/'), None
            return None, result.get("error", "Failed to query bound material.")
        except Exception as e:
            return None, str(e)

    def _extract_definition_path(self, prim_path):
        if not prim_path: return None
        prim_path_norm = prim_path.replace('\\', '/')
        instance_match = re.match(r"^(.*)/instances/inst_([A-Z0-9]{16}(?:_[0-9]+)?)(?:_[0-9]+)?(?:/.*)?$", prim_path_norm)
        if instance_match:
            base_path, mesh_id_part = instance_match.groups()
            return f"{base_path}/meshes/mesh_{mesh_id_part}"
        mesh_subpath_match = re.match(r"^(.*(?:/meshes|/Mesh|/Geom)/mesh_[A-Z0-9]{16}(?:_[0-9]+)?)(?:/.*)?$", prim_path_norm)
        if mesh_subpath_match:
            return mesh_subpath_match.group(1)
        return None

    def _get_mesh_file_path_from_prim(self, prim_path_to_query):
        if not prim_path_to_query: return None, None, "Prim path empty.", 0
        try:
            encoded_prim_path = urllib.parse.quote(prim_path_to_query.replace(os.sep, '/'), safe='/')
            paths_result = self.make_request('GET', f"/stagecraft/assets/{encoded_prim_path}/file-paths")
            
            if paths_result.get("success") and isinstance(paths_result.get("data"), dict):
                data = paths_result["data"]
                potential_paths_data = data.get("reference_paths", data.get("asset_paths", []))
                
                abs_context = None
                rel_mesh = None

                for entry in potential_paths_data:
                    files = []
                    if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], list): files = entry[1]
                    elif isinstance(entry, list): files = entry
                    elif isinstance(entry, str): files = [entry]

                    for f in files:
                        if isinstance(f, str):
                            if os.path.isabs(f): abs_context = f.replace('\\', '/')
                            elif any(f.lower().endswith(ext) for ext in ['.usd', '.usda', '.usdc', '.obj', '.fbx', '.gltf', '.glb']):
                                rel_mesh = f.replace('\\', '/')
                    
                    if abs_context and rel_mesh: break
                
                if rel_mesh: return rel_mesh, abs_context, None, paths_result.get('status_code')
                return None, None, "Could not determine paths.", paths_result.get('status_code')
            
            return None, None, paths_result.get('error'), paths_result.get('status_code')
        except Exception as e:
            return None, None, str(e), 0

    def get_selected_asset_details(self):
        self._log_info("Getting selected asset details from Remix...")
        result = self.make_request('GET', "/stagecraft/assets/", params={"selection": "true", "filter_session_assets": "false", "exists": "true"})
        if not result["success"]:
            return None, None, None, result.get("error")
        
        asset_paths = result.get("data", {}).get("prim_paths", result.get("data", {}).get("asset_paths", []))
        if not asset_paths: return None, None, None, "No selection."

        material_prim, mesh_prim_initial = None, None
        for path in asset_paths:
            p_norm = path.replace('\\', '/')
            if p_norm.endswith("/Shader"):
                material_prim = os.path.dirname(p_norm)
                continue
            if ("/Looks/" in p_norm or "/materials/" in p_norm or "/Material/" in p_norm) and "/PreviewSurface" not in p_norm and not material_prim:
                material_prim = p_norm
                continue
            if "/instances/inst_" in p_norm or "/meshes/" in p_norm or "/Mesh/" in p_norm or "/Geom/" in p_norm:
                if not mesh_prim_initial: mesh_prim_initial = p_norm
        
        if mesh_prim_initial and not material_prim:
            path_for_lookup = self._extract_definition_path(mesh_prim_initial) or mesh_prim_initial
            material_prim, _ = self.get_material_from_mesh(path_for_lookup)

        if not material_prim: return None, None, None, "Could not identify Material Prim."

        # Try finding mesh file path
        prim_paths_to_try = []
        if mesh_prim_initial:
            prim_paths_to_try.append(mesh_prim_initial)
            dp = self._extract_definition_path(mesh_prim_initial)
            if dp and dp not in prim_paths_to_try: prim_paths_to_try.append(dp)
        if material_prim not in prim_paths_to_try: prim_paths_to_try.append(material_prim)

        mesh_file, context_file, last_err = None, None, "No mesh query attempted."
        for p in prim_paths_to_try:
            m, c, err, _ = self._get_mesh_file_path_from_prim(p)
            if m:
                mesh_file, context_file = m, c
                break
            if err: last_err = err

        if not mesh_file:
            return None, material_prim, None, f"Could not find mesh file. {last_err}"

        return mesh_file, material_prim, context_file, None

    def get_material_textures(self, material_prim):
        if not material_prim: return None, "Material prim missing."
        encoded = urllib.parse.quote(str(material_prim).replace(os.sep, "/"), safe="/")
        res = self.make_request("GET", f"/stagecraft/assets/{encoded}/textures")
        if res.get("success") and isinstance(res.get("data"), dict):
             return res["data"].get("textures", []), None
        return None, res.get("error", "Failed to get textures.")

    def ingest_texture(self, pbr_type, texture_file_path, project_output_dir_abs):
        self._log_info(f"Ingesting {pbr_type}: {self.safe_basename(texture_file_path)}")
        
        if not os.path.isfile(texture_file_path):
             return None, f"File not found: {texture_file_path}"
        
        settings = self.settings_getter()
        output_subfolder = settings.get("remix_output_subfolder", "Textures/PainterConnector_Ingested").strip('/\\')
        target_ingest_dir_abs = os.path.normpath(os.path.join(project_output_dir_abs, output_subfolder))
        
        try: os.makedirs(target_ingest_dir_abs, exist_ok=True)
        except Exception as e: return None, f"Failed to create directory: {e}"

        abs_texture_path = os.path.abspath(texture_file_path).replace(os.sep, '/')
        target_ingest_dir_api = os.path.abspath(target_ingest_dir_abs).replace(os.sep, '/')
        
        ingest_type = PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP.get(pbr_type.lower(), "DIFFUSE")
        
        ingest_payload = {
            "executor": 1, 
            "name": f"Ingest_{pbr_type}_{self.safe_basename(abs_texture_path)}",
            "context_plugin": {
                "name": "TextureImporter",
                "data": {
                    "context_name": "ingestcraft_browser",
                    "input_files": [[abs_texture_path, ingest_type]],
                    "output_directory": target_ingest_dir_api,
                    "allow_empty_input_files_list": True,
                    "data_flows": [
                        {"name": "InOutData", "push_output_data": True, "channel": "ingestion_output"},
                        {"name": "InOutData", "push_output_data": True, "channel": "cleanup_files"},
                        {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"}
                    ],
                    "hide_context_ui": True,
                    "create_context_if_not_exist": True,
                    "expose_mass_ui": False,
                    "cook_mass_template": True
                }
            },
            "check_plugins": [
                {
                    "name": "ConvertToDDS",
                    "selector_plugins": [{"name": "AllShaders", "data": {}}],
                    "data": {
                        "data_flows": [
                            {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "ingestion_output"},
                            {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "cleanup_files"},
                            {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"}
                        ]
                    },
                    "stop_if_fix_failed": True,
                    "context_plugin": {"name": "CurrentStage", "data": {}}
                }
            ],
            "resultor_plugins": [
                {"name": "FileCleanup", "data": {"channel": "cleanup_files", "cleanup_output": False}},
                {"name": "FileMetadataWritter", "data": {"channel": "write_metadata"}}
            ]
        }

        res = self.make_request("POST", "/ingestcraft/mass-validator/queue/material", json_payload=ingest_payload)
        if not res["success"]: return None, res.get("error")

        # Parse response to find output path
        original_base = os.path.splitext(self.safe_basename(texture_file_path))[0]
        if original_base.lower().endswith(".rtex"): original_base = os.path.splitext(original_base)[0]
        
        output_paths = []
        data = res.get("data", {})
        if "completed_schemas" in data:
            for schema in data["completed_schemas"]:
                 plugin_results = [schema.get("context_plugin", {})] + schema.get("check_plugins", [])
                 for pr in plugin_results:
                     for flow in pr.get("data", {}).get("data_flows", []):
                         if flow.get("channel") == "ingestion_output":
                             output_paths.extend(flow.get("output_data", []))
        
        if not output_paths and "content" in data:
             output_paths.extend(data["content"])

        def _normalize_ingest_output_stem(dds_path_str: str):
            """
            RTX Remix ingest commonly emits filenames like:
              <stem>.<channel>.rtex.dds  (e.g. foo.a.rtex.dds, foo.n.rtex.dds)
            We want to match <stem> back to the input <original_base>.
            """
            base = os.path.splitext(self.safe_basename(dds_path_str))[0]  # strip .dds
            if base.lower().endswith(".rtex"):
                base = os.path.splitext(base)[0]  # strip .rtex

            # Optional single-letter channel suffix after a dot (a/r/m/h/n/e/...)
            suffix_letter = None
            m = re.match(r"^(.*)\.([a-z])$", base, flags=re.IGNORECASE)
            if m:
                base_no_suffix = m.group(1)
                suffix_letter = m.group(2).lower()
            else:
                base_no_suffix = base

            return base_no_suffix, suffix_letter

        # Expected output suffix letter per pbr type (best-effort)
        expected_suffix = {
            "albedo": "a",
            "normal": "n",
            "roughness": "r",
            "metallic": "m",
            "height": "h",
            "emissive": "e",
            "ao": "o",
            "opacity": "o",
        }.get(str(pbr_type).lower())

        ingested_path = None
        fallback_match = None

        for p in output_paths:
            if not isinstance(p, str):
                continue
            if not p.lower().endswith((".dds", ".rtex.dds")):
                continue

            base_no_suffix, suffix_letter = _normalize_ingest_output_stem(p)
            if base_no_suffix.lower() != original_base.lower():
                continue

            # Prefer the expected suffix when present; otherwise accept as fallback.
            if expected_suffix and suffix_letter == expected_suffix:
                ingested_path = p
                break
            if not expected_suffix:
                ingested_path = p
                break

            # Keep a fallback if the base matches but suffix didn't
            if fallback_match is None:
                fallback_match = p

        if not ingested_path and fallback_match:
            ingested_path = fallback_match

        if not ingested_path: return None, "Could not identify output path from API response."

        final_path = os.path.normpath(ingested_path) if os.path.isabs(ingested_path) else os.path.normpath(os.path.join(target_ingest_dir_api.replace('/', os.sep), ingested_path))
        if not os.path.isfile(final_path): return None, f"File missing: {final_path}"
        
        return final_path, None

    def get_current_edit_target(self):
        self._log_info("Getting current edit target layer from Remix...")
        result = self.make_request('GET', "/stagecraft/layers/target")
        layer_id = result.get("data", {}).get("layer_id") if result["success"] and isinstance(result.get("data"), dict) else None
        
        if not layer_id:
            result_proj = self.make_request('GET', "/stagecraft/project/")
            layer_id = result_proj.get("data", {}).get("layer_id") if result_proj["success"] and isinstance(result_proj.get("data"), dict) else None

        if isinstance(layer_id, str) and layer_id.strip():
            return os.path.normpath(layer_id.replace('\\', '/')), None
        
        return None, "Could not determine edit layer."

    def save_layer(self, layer_id_abs_path):
        if not layer_id_abs_path: return False, "Layer ID missing."
        
        # Verify layer first
        current_layer, err = self.get_current_edit_target()
        if err or not current_layer: return False, f"Could not verify layer: {err}"
        
        encoded = urllib.parse.quote(current_layer.replace(os.sep, '/'), safe=':/')
        result = self.make_request('POST', f"/stagecraft/layers/{encoded}/save")
        
        if result["success"]: return True, None
        return False, result.get("error", "Save failed.")

    def update_textures_batch(self, textures_to_update):
        if not textures_to_update: return True, "No textures."
        
        payload_list = []
        path_errors = []
        for usd_attr, ingested_path in textures_to_update:
            if not ingested_path or not os.path.isabs(ingested_path):
                path_errors.append(f"Path not absolute: {usd_attr}")
                continue
            payload_list.append([usd_attr.replace('\\', '/'), ingested_path.replace(os.sep, '/')])
            
        if not payload_list: return False, "No valid paths."
        
        payload = {"force": True, "textures": payload_list}
        result = self.make_request('PUT', '/stagecraft/textures/', json_payload=payload)
        
        if not result["success"]:
            return False, result.get("error", "Batch update failed.")
        
        if path_errors:
            return True, f"Success with warnings: {path_errors}"
        return True, None

    def ping(self, timeout=2.0):
        """
        Fast health check for the Remix API endpoint.
        Uses a short timeout and a single attempt to keep UI responsive.
        """
        res = self.make_request("GET", "/stagecraft/project/", retries=1, delay=0, timeout=timeout)
        if res.get("success"):
            return True, "Connected"
        return False, res.get("error") or "Connection failed"