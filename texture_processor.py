import os
import sys
import struct
import subprocess
import re
import ntpath

# Hard ceilings so a stuck child cannot freeze Painter forever.
TEXCONV_TIMEOUT_SECONDS = 180
BLENDER_TIMEOUT_SECONDS = 900

_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Uncompressed and RLE color-mapped, true-color and grayscale TGA image types.
_TGA_IMAGE_TYPES = {1, 2, 3, 9, 10, 11}


def read_image_size(path):
    """(width, height) from a PNG, DDS or TGA header, or (0, 0) if unknown.

    Header parsing keeps this independent of Pillow, which is only needed for
    pixel work.
    """
    try:
        with open(path, 'rb') as f:
            header = f.read(24)
    except OSError:
        return 0, 0
    if header[:8] == _PNG_SIGNATURE and len(header) >= 24:
        w, h = struct.unpack('>II', header[16:24])
        return int(w), int(h)
    if header[:4] == b'DDS ' and len(header) >= 20:
        h, w = struct.unpack('<II', header[12:20])
        return int(w), int(h)
    # TGA has no signature; trust the extension and sanity-check the header.
    if str(path).lower().endswith(".tga") and len(header) >= 18 and header[2] in _TGA_IMAGE_TYPES:
        w, h = struct.unpack('<HH', header[12:16])
        return int(w), int(h)
    return 0, 0


def is_octahedral_normal_name(path):
    """Remix's ingest writes octahedral normals as ``*_OTH_Normal.n.rtex.dds``.

    "_oth" must be a whole token, so names like ``wood_other_normal`` don't match.
    """
    return re.search(r"_oth(?=[._]|$)", ntpath.basename(str(path)).lower()) is not None


def _subprocess_window_flags():
    startupinfo, creationflags = None, 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


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
    def _truncate(text, limit=400):
        if not text: return ""
        text = str(text).strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "...(truncated)"

    @staticmethod
    def safe_basename(path):
        if not path: return ""
        try: return ntpath.basename(str(path))
        except Exception: return str(path)

    def _run_texconv(self, command, label):
        self._log_info(f"  Running texconv: {' '.join(command)}")
        startupinfo, creationflags = _subprocess_window_flags()
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False,
                startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore',
                timeout=TEXCONV_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"texconv timed out after {TEXCONV_TIMEOUT_SECONDS}s on {label}")
        except OSError as e:
            raise RuntimeError(f"Error running texconv: {e}")
        if result.returncode != 0:
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"texconv failed (Code {result.returncode}). Stdout: {stdout} Stderr: {stderr}")
        return result

    def convert_dds_to_png(self, texconv_exe, dds_file, output_png_target_name_base, output_dir_override=None, force_rgba=False):
        """Convert a DDS to PNG next to it (or into ``output_dir_override``).

        ``force_rgba`` expands the result to 8-bit RGBA. Two-channel formats
        (BC5 normal maps) need it: PNG cannot store R8G8, so texconv fails with
        0x80070032 ("The request is not supported").
        """
        if not texconv_exe or not os.path.isfile(texconv_exe):
            raise RuntimeError(f"texconv.exe path is not configured or invalid: {texconv_exe}")
        if not os.path.isfile(dds_file):
            raise RuntimeError(f"Input DDS file not found: {dds_file}")

        output_dir = output_dir_override if output_dir_override else os.path.dirname(dds_file)
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(self.safe_basename(dds_file))[0]
        expected_output_path = os.path.join(output_dir, base_name + ".png")

        command = [texconv_exe, "-ft", "png", "-o", output_dir, "-y", "-nologo"]
        if force_rgba:
            command += ["-f", "R8G8B8A8_UNORM"]
        command.append(dds_file)

        try:
            self._run_texconv(command, self.safe_basename(dds_file))
        except RuntimeError as e:
            if force_rgba:
                self._log_error(str(e))
                raise
            # Unknown 2-channel/float formats: retry once with an RGBA expansion.
            self._log_warning(f"{e} -- retrying with RGBA output.")
            return self.convert_dds_to_png(texconv_exe, dds_file, output_png_target_name_base, output_dir_override, force_rgba=True)

        if not os.path.exists(expected_output_path):
            raise RuntimeError(f"texconv reported success but output missing: {expected_output_path}")
        return expected_output_path

    def resize_image(self, texconv_exe, image_path, width, height):
        """Resize a PNG or TGA in place with texconv (cubic filtering).

        The output keeps the input's format, so texconv overwrites the file
        that will be ingested instead of writing a sibling.
        """
        if not texconv_exe or not os.path.isfile(texconv_exe):
            raise RuntimeError("texconv.exe not found; cannot resize.")
        file_type = os.path.splitext(image_path)[1].lstrip(".").lower() or "png"
        command = [
            texconv_exe, "-w", str(int(width)), "-h", str(int(height)),
            "-ft", file_type, "-if", "CUBIC", "-y", "-nologo",
            "-o", os.path.dirname(image_path), image_path,
        ]
        self._run_texconv(command, self.safe_basename(image_path))

    # --- Value remaps ---

    def _first_band(self, image_path):
        """The image's first channel as 8-bit grayscale. Single-channel maps can
        arrive as RGB(A) with the data in red (texconv's RGBA expansion)."""
        Image, _ = self._image_modules()
        with Image.open(image_path) as img:
            band = img.split()[0]
            band.load()
        return band if band.mode == "L" else band.convert("L")

    def anisotropy_to_remix(self, image_path):
        """Painter Anisotropy Level (0 = isotropic) -> Remix anisotropy (0.5 = isotropic).

        AperturePBR decodes the map as ``texel * 2 - 1`` (-1..1). Painter's
        level has no sign, so it maps onto the positive half: 0 -> 0.5, 1 -> 1.
        """
        self._first_band(image_path).point(lambda v: (v + 256) // 2).save(image_path)

    def anisotropy_from_remix(self, image_path):
        """Inverse of anisotropy_to_remix; negative Remix values keep their magnitude."""
        self._first_band(image_path).point(lambda v: min(255, abs(2 * v - 255))).save(image_path)

    # --- Normal maps ---

    @staticmethod
    def _image_modules():
        from PIL import Image, ImageMath
        return Image, ImageMath

    def convert_remix_normal(self, png_path, octahedral, source_directx=True, target_opengl=True):
        """Rewrite a normal map pulled from Remix as a tangent-space RGB normal.

        Remix stores ingested normals octahedrally (2 channels). The inverse of
        Remix's ``hemisphereDirectionToUnsignedOctahedral`` is:
            a, b = R - 0.5, G - 0.5
            n = normalize(a + b, a - b, 1 - |a + b| - |a - b|)
        with Y in DirectX convention (green down). Non-octahedral two-channel
        maps get their Z rebuilt from X/Y. Green is flipped to match the
        project's normal format.
        """
        Image, ImageMath = self._image_modules()
        ev = ImageMath.lambda_eval

        with Image.open(png_path) as img:
            rgb = img.convert("RGB")
        r, g, b = rgb.split()

        to_unit = lambda band: ev(lambda e: e["float"](e["c"]) / 255.0, c=band)
        if octahedral:
            a = ev(lambda e: e["v"] - 0.5, v=to_unit(r))
            c = ev(lambda e: e["v"] - 0.5, v=to_unit(g))
            x = ev(lambda e: e["a"] + e["c"], a=a, c=c)
            y = ev(lambda e: e["a"] - e["c"], a=a, c=c)
            z = ev(lambda e: 1.0 - abs(e["x"]) - abs(e["y"]), x=x, y=y)
            y_is_directx = True
        else:
            x = ev(lambda e: e["v"] * 2.0 - 1.0, v=to_unit(r))
            y = ev(lambda e: e["v"] * 2.0 - 1.0, v=to_unit(g))
            if b.getextrema()[1] == 0:
                z = ev(lambda e: e["max"](1.0 - e["x"] * e["x"] - e["y"] * e["y"], 0.0) ** 0.5, x=x, y=y)
            else:
                z = ev(lambda e: e["v"] * 2.0 - 1.0, v=to_unit(b))
            y_is_directx = source_directx

        length = ev(lambda e: e["max"]((e["x"] * e["x"] + e["y"] * e["y"] + e["z"] * e["z"]) ** 0.5, 1e-6), x=x, y=y, z=z)
        y_sign = -1.0 if (y_is_directx == target_opengl) else 1.0

        def to_byte(component, sign=1.0):
            return ev(
                lambda e: e["convert"]((e["n"] / e["l"] * e["s"] * 0.5 + 0.5) * 255.0 + 0.5, "L"),
                n=component, l=length, s=sign,
            )

        out = Image.merge("RGB", (to_byte(x), to_byte(y, y_sign), to_byte(z)))
        out.save(png_path)
        return png_path

    def extract_alpha(self, png_path, out_path):
        """Save the alpha channel as a grayscale PNG. Returns out_path, or None
        when the image has no meaningful alpha (fully opaque)."""
        Image, _ = self._image_modules()
        with Image.open(png_path) as img:
            if "A" not in img.getbands():
                return None
            alpha = img.getchannel("A")
        if alpha.getextrema()[0] >= 255:
            return None
        alpha.save(out_path)
        return out_path

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

    def unwrap_mesh_with_blender(self, input_mesh_path, output_dir=None):
        """Smart-UV-unwrap a mesh in a background Blender.

        The result goes to ``output_dir`` (default: next to the input). Callers
        should pass a scratch folder: the input usually lives inside the Remix
        project's captures, which must not be modified.
        """
        self._log_info(f"Unwrapping mesh: {self.safe_basename(input_mesh_path)}")
        settings = self.settings_getter()
        blender_exe = settings.get("blender_executable_path")
        unwrap_script_path = self._get_blender_unwrap_script_path()

        if not blender_exe or not os.path.isfile(blender_exe):
            self._log_error(f"Blender executable invalid: '{blender_exe}'")
            self._display_message("Auto-unwrap skipped: set the Blender path in Settings > Blender.")
            return None
        if not unwrap_script_path:
            self._display_message("Error: Blender unwrap script not found.")
            return None

        base, ext = os.path.splitext(self.safe_basename(input_mesh_path))
        out_dir = output_dir or os.path.dirname(input_mesh_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self._display_message(f"Error: cannot create unwrap folder: {e}")
            return None
        output_suffix = settings.get("blender_unwrap_output_suffix", "_spUnwrapped")
        # Bundled material groups are .usda wrappers referencing other files;
        # Blender flattens them, so a binary .usd output is fine everywhere.
        out_ext = ".usd" if ext.lower() in (".usd", ".usda", ".usdc") else ext
        output_mesh_path = os.path.join(out_dir, f"{base}{output_suffix}{out_ext}")

        args = [
            "--angle_limit", str(settings.get("blender_smart_uv_angle_limit", 66.0)),
            "--island_margin", str(settings.get("blender_smart_uv_island_margin", 0.003)),
            "--area_weight", str(settings.get("blender_smart_uv_area_weight", 0.0)),
            "--stretch_to_bounds", str(settings.get("blender_smart_uv_stretch_to_bounds", "False"))
        ]

        command = [blender_exe, "--background", "--factory-startup", "--python", unwrap_script_path, "--", input_mesh_path, output_mesh_path] + args
        self._log_info(f"  Executing Blender: {' '.join(command)}")

        try:
            startupinfo, creationflags = _subprocess_window_flags()
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False,
                    startupinfo=startupinfo, creationflags=creationflags,
                    encoding='utf-8', errors='ignore',
                    timeout=BLENDER_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                self._log_error(f"Blender unwrap timed out after {BLENDER_TIMEOUT_SECONDS}s.")
                self._display_message("Error: Blender auto-unwrap timed out.")
                return None

            stdout_text = result.stdout or ""
            stderr_text = result.stderr or ""
            # The unwrap script reports through stdout ("BlenderScript: ERROR: ...");
            # stderr is mostly USD composition warnings.
            script_errors = [ln.strip() for ln in stdout_text.splitlines() if "BlenderScript: ERROR" in ln or "BlenderScript: CRITICAL" in ln]
            if result.returncode != 0 or script_errors or "Error: Python script fail" in stderr_text:
                detail = "; ".join(script_errors) or self._truncate(stderr_text) or f"exit code {result.returncode}"
                self._log_error(f"Blender failed (Code {result.returncode}). {detail}\nStdout tail: {self._truncate(stdout_text[-2000:], 2000)}")
                self._display_message(f"Blender auto-unwrap failed: {self._truncate(detail)}")
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
