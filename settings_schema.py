import os
import tempfile
from typing import Any, Dict, Tuple

from .plugin_info import PLUGIN_ID

DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"
SETTINGS_VERSION = 1


def _detect_texconv_path(plugin_dir: str) -> str:
    try:
        local = os.path.join(plugin_dir, "texconv.exe")
        return local if os.path.isfile(local) else ""
    except Exception:
        return ""


def default_settings(plugin_dir: str) -> Dict[str, Any]:
    """
    Returns default settings (with a few best-effort auto-detections).
    """
    return {
        "settings_version": SETTINGS_VERSION,
        # --- Connection ---
        "api_base_url": DEFAULT_REMIX_API_BASE_URL,
        "poll_timeout": 60.0,
        # --- Logging ---
        "log_level": "info",
        # --- Pull ---
        "use_simple_tiling_mesh_on_pull": False,
        "simple_tiling_mesh_path": "assets/meshes/plane_tiling.usd",
        "painter_import_template_path": "",
        "auto_unwrap_with_blender_on_pull": False,
        # --- Blender unwrap ---
        "blender_executable_path": "",
        "blender_unwrap_script_path": "",
        "blender_unwrap_output_suffix": "_spUnwrapped",
        "blender_smart_uv_angle_limit": 66.0,
        "blender_smart_uv_area_weight": 0.0,
        "blender_smart_uv_island_margin": 0.003,
        "blender_smart_uv_stretch_to_bounds": False,
        # --- Push/Export ---
        "painter_export_path": os.path.join(tempfile.gettempdir(), "RemixConnector_Export"),
        "export_file_format": "png",
        # Optional extra exports (off by default to preserve current behavior)
        "include_opacity_map": False,
        # --- Remix output ---
        "remix_output_subfolder": "Textures/PainterConnector_Ingested",
        # --- Tools ---
        "texconv_path": _detect_texconv_path(plugin_dir),
        # --- Internal / reserved ---
        "plugin_id": PLUGIN_ID,
    }


def _coerce_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _coerce_float(v: Any, default: float) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except Exception:
            return default
    return default


def _coerce_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        return str(v)
    except Exception:
        return default


def sanitize_settings(settings: Dict[str, Any], plugin_dir: str) -> Dict[str, Any]:
    """
    Normalizes types, fills missing defaults, and performs tiny migrations.
    Unknown keys are preserved.
    """
    merged = dict(default_settings(plugin_dir))
    merged.update(settings or {})

    # --- basic type coercions ---
    merged["api_base_url"] = _coerce_str(merged.get("api_base_url"), DEFAULT_REMIX_API_BASE_URL).strip() or DEFAULT_REMIX_API_BASE_URL
    merged["poll_timeout"] = _coerce_float(merged.get("poll_timeout"), 60.0)

    merged["log_level"] = _coerce_str(merged.get("log_level"), "info").strip().lower() or "info"
    if merged["log_level"] not in {"debug", "info", "warning", "error"}:
        merged["log_level"] = "info"

    merged["use_simple_tiling_mesh_on_pull"] = _coerce_bool(merged.get("use_simple_tiling_mesh_on_pull"), False)
    merged["simple_tiling_mesh_path"] = _coerce_str(merged.get("simple_tiling_mesh_path"), "assets/meshes/plane_tiling.usd")
    merged["painter_import_template_path"] = _coerce_str(merged.get("painter_import_template_path"), "")
    merged["auto_unwrap_with_blender_on_pull"] = _coerce_bool(merged.get("auto_unwrap_with_blender_on_pull"), False)

    merged["blender_executable_path"] = _coerce_str(merged.get("blender_executable_path"), "")
    merged["blender_unwrap_script_path"] = _coerce_str(merged.get("blender_unwrap_script_path"), "")
    merged["blender_unwrap_output_suffix"] = _coerce_str(merged.get("blender_unwrap_output_suffix"), "_spUnwrapped") or "_spUnwrapped"
    merged["blender_smart_uv_angle_limit"] = _coerce_float(merged.get("blender_smart_uv_angle_limit"), 66.0)
    merged["blender_smart_uv_area_weight"] = _coerce_float(merged.get("blender_smart_uv_area_weight"), 0.0)
    merged["blender_smart_uv_island_margin"] = _coerce_float(merged.get("blender_smart_uv_island_margin"), 0.003)
    merged["blender_smart_uv_stretch_to_bounds"] = _coerce_bool(merged.get("blender_smart_uv_stretch_to_bounds"), False)

    merged["painter_export_path"] = _coerce_str(merged.get("painter_export_path"), os.path.join(tempfile.gettempdir(), "RemixConnector_Export"))
    merged["export_file_format"] = _coerce_str(merged.get("export_file_format"), "png").strip().lower() or "png"
    if merged["export_file_format"] not in {"png", "tga", "jpg", "jpeg"}:
        merged["export_file_format"] = "png"

    merged["include_opacity_map"] = _coerce_bool(merged.get("include_opacity_map"), False)

    merged["remix_output_subfolder"] = _coerce_str(merged.get("remix_output_subfolder"), "Textures/PainterConnector_Ingested").strip() or "Textures/PainterConnector_Ingested"

    # texconv: if empty/invalid, try local copy
    texconv = _coerce_str(merged.get("texconv_path"), "").strip()
    if texconv and not os.path.isfile(texconv):
        texconv = ""
    if not texconv:
        texconv = _detect_texconv_path(plugin_dir)
    merged["texconv_path"] = texconv

    merged["settings_version"] = SETTINGS_VERSION
    merged["plugin_id"] = PLUGIN_ID
    return merged


def atomic_write_json(path: str, data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Writes JSON atomically (best effort) to prevent corrupt settings on crash.
    """
    import json
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

    tmp_path = None
    try:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, path)
        return True, ""
    except Exception as e:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False, str(e)


