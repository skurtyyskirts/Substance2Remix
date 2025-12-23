import os
import sys
import shutil
import subprocess
import time
import re
import ntpath

class TextureProcessor:
    def __init__(self, settings_getter, logger, message_callback=None):
        self.settings_getter = settings_getter
        self.logger = logger
        self.message_callback = message_callback

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
            try: self.logger.error(msg, exc_info=exc_info)
            except TypeError: self.logger.error(msg)
        elif isinstance(self.logger, dict) and 'error' in self.logger: self.logger['error'](msg)

    def _display_message(self, msg):
        if self.message_callback: self.message_callback(str(msg))
        else: self._log_info(f"UI Message: {msg}")

    @staticmethod
    def safe_basename(path):
        if not path: return ""
        try: return ntpath.basename(str(path))
        except Exception: return str(path)

    @staticmethod
    def _sanitize_filename_stem(name):
        if not name: return ""
        cleaned = str(name).strip()
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        cleaned = cleaned.strip(" .")
        return cleaned[:120]

    @staticmethod
    def _strip_known_texture_extensions(texture_path_or_name):
        if not texture_path_or_name: return ""
        base = TextureProcessor.safe_basename(str(texture_path_or_name).replace("\\", "/"))
        stem = os.path.splitext(base)[0]
        if stem.lower().endswith(".rtex"):
            stem = os.path.splitext(stem)[0]
        return stem

    @staticmethod
    def _strip_ingest_channel_suffix(stem):
        if not stem: return ""
        return re.sub(r"\.[armhnoaodse]$", "", str(stem), flags=re.IGNORECASE)

    def convert_dds_to_png(self, texconv_exe, dds_file, output_png_target_name_base, output_dir_override=None):
        if not texconv_exe or not os.path.isfile(texconv_exe): 
            raise RuntimeError(f"texconv.exe path is not configured or invalid: {texconv_exe}")
        if not os.path.isfile(dds_file): 
            raise RuntimeError(f"Input DDS file not found: {dds_file}")

        output_dir = output_dir_override if output_dir_override else os.path.dirname(dds_file)
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(self.safe_basename(dds_file))[0]
        expected_output_filename = base_name + ".png"
        expected_output_path = os.path.join(output_dir, expected_output_filename)
        
        # Texconv typically overwrites if exists
        command = [texconv_exe, "-ft", "png", "-o", output_dir, "-y", "-nologo", dds_file]
        self._log_info(f"  Running texconv: {' '.join(command)}")
        
        try:
            startupinfo, creationflags = None, 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(command, capture_output=True, text=True, check=False, 
                                  startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore')

            if result.returncode != 0:
                stdout = (result.stdout or "").strip()
                stderr = (result.stderr or "").strip()
                err_msg = (
                    f"texconv failed (Code {result.returncode}). "
                    f"Stdout: {stdout} "
                    f"Stderr: {stderr}"
                )
                self._log_error(err_msg)
                raise RuntimeError(err_msg)

            if not os.path.exists(expected_output_path):
                raise RuntimeError(f"texconv reported success but output missing: {expected_output_path}")
            
            return expected_output_path
        except Exception as e:
            raise RuntimeError(f"Error running texconv: {e}")

    def _get_blender_unwrap_script_path(self):
        settings = self.settings_getter()
        script_path_setting = settings.get("blender_unwrap_script_path")
        if script_path_setting and os.path.isfile(script_path_setting):
            return script_path_setting
        
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            script_path_default = os.path.join(current_dir, "blender_auto_unwrap.py")
            if os.path.isfile(script_path_default):
                return script_path_default
        except Exception: pass
        return None

    def unwrap_mesh_with_blender(self, input_mesh_path):
        self._log_info(f"Unwrapping mesh: {self.safe_basename(input_mesh_path)}")
        settings = self.settings_getter()
        blender_exe = settings.get("blender_executable_path")
        unwrap_script_path = self._get_blender_unwrap_script_path()

        if not blender_exe or not os.path.isfile(blender_exe):
            self._log_error(f"Blender executable invalid: '{blender_exe}'")
            self._display_message("Error: Blender executable path invalid.")
            return None
        if not unwrap_script_path:
            self._display_message("Error: Blender unwrap script not found.")
            return None

        base, ext = os.path.splitext(input_mesh_path)
        output_suffix = settings.get("blender_unwrap_output_suffix", "_spUnwrapped")
        output_mesh_path = f"{base}{output_suffix}{ext}"
        
        args = [
            "--angle_limit", str(settings.get("blender_smart_uv_angle_limit", 66.0)),
            "--island_margin", str(settings.get("blender_smart_uv_island_margin", 0.003)),
            "--area_weight", str(settings.get("blender_smart_uv_area_weight", 0.0)),
            "--stretch_to_bounds", str(settings.get("blender_smart_uv_stretch_to_bounds", "False"))
        ]
        
        command = [blender_exe, "--background", "--python", unwrap_script_path, "--", input_mesh_path, output_mesh_path] + args
        self._log_info(f"  Executing Blender: {' '.join(command)}")

        try:
            startupinfo, creationflags = None, 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(command, capture_output=True, text=True, check=False,
                                  startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore')
            
            if result.returncode != 0 or "Error: Python script fail" in result.stderr:
                self._log_error(f"Blender failed (Code {result.returncode}). Stderr: {result.stderr}")
                self._display_message("Error: Blender auto-unwrap failed.")
                return None
            
            if os.path.exists(output_mesh_path):
                self._log_info(f"Blender unwrap success: {output_mesh_path}")
                return output_mesh_path
            
            self._log_error("Blender finished but output missing.")
            return None
        except Exception as e:
            self._log_error(f"Blender execution exception: {e}", exc_info=True)
            self._display_message(f"Error: Blender exception: {e}")
            return None

    def _force_push_root_conflicts(self, root, ingest_dir_abs):
        if not root or not ingest_dir_abs or not os.path.isdir(ingest_dir_abs): return False
        root_l = root.lower()
        try:
            for fname in os.listdir(ingest_dir_abs):
                fl = fname.lower()
                if not (fl.endswith(".dds") or fl.endswith(".rtex.dds")): continue
                if not fl.startswith(root_l): continue
                if fl[len(root_l):len(root_l)+1] in ("", ".", "_", "-"): return True
        except Exception: pass
        return False

    def choose_non_overwriting_root(self, desired_root, ingest_dir_abs):
        desired_root = self._sanitize_filename_stem(desired_root)
        if not desired_root: return desired_root
        candidate = desired_root
        idx = 1
        while self._force_push_root_conflicts(candidate, ingest_dir_abs):
            candidate = f"{desired_root}_{idx}"
            idx += 1
            if idx > 9999:
                candidate = f"{desired_root}_{int(time.time())}"
                break
        return candidate

    def copy_texture_with_forced_root(self, exported_texture_path, forced_root, pbr_type, temp_export_root):
        if not exported_texture_path or not os.path.isfile(exported_texture_path):
            return None, f"Exported texture missing: '{exported_texture_path}'"
        
        forced_root = self._sanitize_filename_stem(forced_root)
        if not forced_root: return None, "Forced root name invalid."

        ext = os.path.splitext(exported_texture_path)[1] or ".png"
        temp_dir = os.path.join(temp_export_root, "_RemixConnector_ForcePush_Renamed", str(pbr_type))
        
        try:
            os.makedirs(temp_dir, exist_ok=True)
            dest_path = os.path.join(temp_dir, f"{forced_root}{ext}")
            shutil.copy2(exported_texture_path, dest_path)
            return dest_path, None
        except Exception as e:
            return None, f"Failed to copy/rename: {e}"

