"""Tests for texture_processor.py DDS pipeline."""
import os
import struct
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import texture_processor  # noqa: E402
from texture_processor import TextureProcessor, TEXCONV_TIMEOUT_SECONDS, BLENDER_TIMEOUT_SECONDS  # noqa: E402


def _make_processor(settings=None):
    settings = settings or {}
    return TextureProcessor(settings_getter=lambda: settings, logger=MagicMock())


class TestSanitizeFilename(unittest.TestCase):
    def test_strips_illegal_chars(self):
        tp = _make_processor()
        result = tp._sanitize_filename_stem("foo<bar>:baz")
        for ch in "<>:":
            self.assertNotIn(ch, result)

    def test_truncates_long_names(self):
        tp = _make_processor()
        result = tp._sanitize_filename_stem("a" * 200)
        self.assertLessEqual(len(result), 120)

    def test_empty_returns_empty(self):
        self.assertEqual(_make_processor()._sanitize_filename_stem(""), "")


class TestImageHeaders(unittest.TestCase):
    def test_png_and_dds_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "a.png")
            with open(png, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 256, 1024))
            dds = os.path.join(tmp, "a.dds")
            with open(dds, "wb") as f:
                f.write(b"DDS " + struct.pack("<II", 124, 0) + struct.pack("<II", 512, 2048))
            self.assertEqual(texture_processor.read_image_size(png), (256, 1024))
            self.assertEqual(texture_processor.read_image_size(dds), (2048, 512))
            self.assertEqual(texture_processor.read_image_size(os.path.join(tmp, "missing.png")), (0, 0))

    def test_octahedral_name_detection(self):
        self.assertTrue(texture_processor.is_octahedral_normal_name("C:/x/H_OTH_Normal.n.rtex.dds"))
        self.assertTrue(texture_processor.is_octahedral_normal_name("C:/x/H_oth.n.rtex.dds"))
        self.assertFalse(texture_processor.is_octahedral_normal_name("C:/x/H_normal.n.rtex.dds"))
        self.assertFalse(texture_processor.is_octahedral_normal_name("C:/x/wood_other_normal.png"))


def _pil_available():
    try:
        from PIL import Image, ImageMath  # noqa: F401
        Image.new("RGB", (1, 1))
        return True
    except Exception:
        return False


def _remix_octahedral_encode(n, opengl):
    """omni.flux.utils.octahedral_converter, for one normal in [-1, 1]."""
    x = n[0]
    y = -n[1] if opengl else n[1]
    z = abs(n[2])
    s = 0.5 / (abs(x) + abs(y) + z)
    return (x + y) * s + 0.5, (x - y) * s + 0.5


@unittest.skipUnless(_pil_available(), "Pillow binary for this Python is not available")
class TestNormalConversion(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.Image = Image
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _decode(self, pixels, size, **kwargs):
        path = os.path.join(self.tmp, "n.png")
        img = self.Image.new("RGB", size)
        img.putdata(pixels)
        img.save(path)
        _make_processor().convert_remix_normal(path, **kwargs)
        return [[c / 255.0 * 2 - 1 for c in px] for px in self.Image.open(path).convert("RGB").getdata()]

    def test_octahedral_round_trip(self):
        normals = [(0.0, 0.0, 1.0), (0.6, 0.0, 0.8), (0.0, -0.6, 0.8), (0.48, 0.36, 0.8)]
        for src_gl in (True, False):
            pixels = []
            for n in normals:
                r, g = _remix_octahedral_encode(n, src_gl)
                pixels.append((int(r * 255 + 0.5), int(g * 255 + 0.5), 0))
            out = self._decode(pixels, (len(normals), 1), octahedral=True, target_opengl=src_gl)
            for got, want in zip(out, normals):
                for a, b in zip(got, want):
                    self.assertAlmostEqual(a, b, delta=0.03)

    def test_tangent_two_channel_rebuilds_z_and_flips_green(self):
        # A DirectX map with an empty blue channel (BC5), converted to OpenGL.
        x, y = 0.6, 0.0
        px = (int((x + 1) / 2 * 255 + 0.5), int((0.4 + 1) / 2 * 255 + 0.5), 0)
        out = self._decode([px], (1, 1), octahedral=False, source_directx=True, target_opengl=True)[0]
        self.assertAlmostEqual(out[0], 0.6, delta=0.03)
        self.assertAlmostEqual(out[1], -0.4, delta=0.03)
        self.assertGreater(out[2], 0.6)

    def test_extract_alpha(self):
        src = os.path.join(self.tmp, "albedo.png")
        self.Image.new("RGBA", (2, 1), (255, 0, 0, 128)).save(src)
        out = _make_processor().extract_alpha(src, os.path.join(self.tmp, "opacity.png"))
        self.assertEqual(self.Image.open(out).getpixel((0, 0)), 128)
        opaque = os.path.join(self.tmp, "opaque.png")
        self.Image.new("RGBA", (2, 1), (255, 0, 0, 255)).save(opaque)
        self.assertIsNone(_make_processor().extract_alpha(opaque, os.path.join(self.tmp, "x.png")))


class TestConvertDdsToPng(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tp = _make_processor()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_raises_if_texconv_missing(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.tp.convert_dds_to_png("/nonexistent/texconv.exe", "/some/file.dds", "output")
        self.assertIn("texconv.exe", str(ctx.exception))

    def test_raises_if_dds_missing(self):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        open(fake_texconv, "w").close()
        with self.assertRaises(RuntimeError) as ctx:
            self.tp.convert_dds_to_png(fake_texconv, "/nonexistent/foo.dds", "foo")
        self.assertIn("not found", str(ctx.exception))

    @patch("subprocess.run")
    def test_raises_on_nonzero_returncode(self, mock_run):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.dds")
        open(fake_texconv, "w").close()
        open(fake_dds, "w").close()
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error detail")
        with self.assertRaises(RuntimeError) as ctx:
            self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo")
        self.assertIn("texconv failed", str(ctx.exception))

    @patch("subprocess.run")
    def test_raises_on_timeout(self, mock_run):
        import subprocess
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.dds")
        open(fake_texconv, "w").close()
        open(fake_dds, "w").close()
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="texconv", timeout=TEXCONV_TIMEOUT_SECONDS)
        with self.assertRaises(RuntimeError) as ctx:
            self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo")
        self.assertIn("timed out", str(ctx.exception))
        self.assertIn(str(TEXCONV_TIMEOUT_SECONDS), str(ctx.exception))

    @patch("subprocess.run")
    def test_raises_if_output_missing_after_success(self, mock_run):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.dds")
        open(fake_texconv, "w").close()
        open(fake_dds, "w").close()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with self.assertRaises(RuntimeError) as ctx:
            self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo")
        self.assertIn("output missing", str(ctx.exception))

    @patch("subprocess.run")
    def test_success_returns_output_path(self, mock_run):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.dds")
        expected_png = os.path.join(self.tmpdir, "foo.png")
        open(fake_texconv, "w").close()
        open(fake_dds, "w").close()
        open(expected_png, "w").close()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo")
        self.assertEqual(result, expected_png)
        self.assertNotIn("-f", mock_run.call_args[0][0])

    @patch("subprocess.run")
    def test_failure_retries_with_rgba_expansion(self, mock_run):
        # BC5 (R8G8) can't be written as PNG; texconv answers 0x80070032.
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.n.rtex.dds")
        for p in (fake_texconv, fake_dds, os.path.join(self.tmpdir, "foo.n.rtex.png")):
            open(p, "w").close()
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="FAILED (80070032: The request is not supported.)", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo")
        second = mock_run.call_args_list[1][0][0]
        self.assertIn("R8G8B8A8_UNORM", second)

    @patch("subprocess.run")
    def test_force_rgba_passes_format(self, mock_run):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        fake_dds = os.path.join(self.tmpdir, "foo.dds")
        for p in (fake_texconv, fake_dds, os.path.join(self.tmpdir, "foo.png")):
            open(p, "w").close()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.tp.convert_dds_to_png(fake_texconv, fake_dds, "foo", force_rgba=True)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-f") + 1], "R8G8B8A8_UNORM")
        self.assertEqual(cmd[-1], fake_dds)

    @patch("subprocess.run")
    def test_resize_png_command(self, mock_run):
        fake_texconv = os.path.join(self.tmpdir, "texconv.exe")
        open(fake_texconv, "w").close()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        png = os.path.join(self.tmpdir, "a.png")
        self.tp.resize_png(fake_texconv, png, 512, 2048)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-w") + 1], "512")
        self.assertEqual(cmd[cmd.index("-h") + 1], "2048")
        self.assertEqual(cmd[-1], png)


class TestBlenderUnwrap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.blender = os.path.join(self.tmpdir, "blender.exe")
        open(self.blender, "w").close()
        self.mesh = os.path.join(self.tmpdir, "captures", "mesh_A.usd")
        os.makedirs(os.path.dirname(self.mesh))
        open(self.mesh, "w").close()
        self.messages = []
        self.tp = TextureProcessor(lambda: {"blender_executable_path": self.blender}, MagicMock(), self.messages.append)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("subprocess.run")
    def test_output_goes_to_output_dir_not_next_to_capture(self, mock_run):
        out_dir = os.path.join(self.tmpdir, "work")
        expected = os.path.join(out_dir, "mesh_A_spUnwrapped.usd")

        def fake_run(cmd, **kw):
            open(expected, "w").close()
            return MagicMock(returncode=0, stdout="BlenderScript: INFO: ok", stderr="")

        mock_run.side_effect = fake_run
        result = self.tp.unwrap_mesh_with_blender(self.mesh, output_dir=out_dir)
        self.assertEqual(result, expected)
        self.assertEqual(os.listdir(os.path.dirname(self.mesh)), ["mesh_A.usd"])

    @patch("subprocess.run")
    def test_script_errors_from_stdout_are_reported(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Warning: USD noise",
            stdout='BlenderScript: ERROR: keyword "primvars_interpolation" unrecognized')
        self.assertIsNone(self.tp.unwrap_mesh_with_blender(self.mesh, output_dir=self.tmpdir))
        self.assertIn("primvars_interpolation", self.messages[-1])

    def test_missing_blender_is_reported(self):
        tp = TextureProcessor(lambda: {"blender_executable_path": ""}, MagicMock(), self.messages.append)
        self.assertIsNone(tp.unwrap_mesh_with_blender(self.mesh))
        self.assertIn("Blender", self.messages[-1])


class TestChooseNonOverwritingRoot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tp = _make_processor()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_desired_root_when_no_conflict(self):
        result = self.tp.choose_non_overwriting_root("mymat", self.tmpdir)
        self.assertEqual(result, "mymat")

    def test_appends_index_on_conflict(self):
        open(os.path.join(self.tmpdir, "mymat.dds"), "w").close()
        result = self.tp.choose_non_overwriting_root("mymat", self.tmpdir)
        self.assertEqual(result, "mymat_1")

    def test_returns_desired_when_ingest_dir_missing(self):
        result = self.tp.choose_non_overwriting_root("foo", "/nonexistent/dir")
        self.assertEqual(result, "foo")


if __name__ == "__main__":
    unittest.main()

class TestForcePushRootConflicts(unittest.TestCase):
    def setUp(self):
        self.tp = _make_processor()

    def test_invalid_args_returns_false(self):
        self.assertFalse(self.tp._force_push_root_conflicts("", "/fake/dir"))
        self.assertFalse(self.tp._force_push_root_conflicts(None, "/fake/dir"))
        self.assertFalse(self.tp._force_push_root_conflicts("root", ""))
        self.assertFalse(self.tp._force_push_root_conflicts("root", None))

    @patch("os.path.isdir")
    def test_missing_directory_returns_false(self, mock_isdir):
        mock_isdir.return_value = False
        self.assertFalse(self.tp._force_push_root_conflicts("root", "/fake/dir"))

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_conflicting_names_return_true(self, mock_listdir, mock_isdir):
        mock_isdir.return_value = True

        # Exact match + extension
        mock_listdir.return_value = ["mymat.dds"]
        self.assertTrue(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

        # Different case
        mock_listdir.return_value = ["MYMAT.DDS"]
        self.assertTrue(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

        # Underscore suffix
        mock_listdir.return_value = ["mymat_albedo.dds"]
        self.assertTrue(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

        # Hyphen suffix
        mock_listdir.return_value = ["mymat-normal.rtex.dds"]
        self.assertTrue(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_non_conflicting_names_return_false(self, mock_listdir, mock_isdir):
        mock_isdir.return_value = True

        # Starts with root but not followed by delimiter
        mock_listdir.return_value = ["mymatalbedo.dds"]
        self.assertFalse(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

        # Partial root match
        mock_listdir.return_value = ["myma.dds"]
        self.assertFalse(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

        # Different extension
        mock_listdir.return_value = ["mymat.png"]
        self.assertFalse(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_exception_during_listdir_returns_false(self, mock_listdir, mock_isdir):
        mock_isdir.return_value = True
        mock_listdir.side_effect = PermissionError("Access denied")
        self.assertFalse(self.tp._force_push_root_conflicts("mymat", "/fake/dir"))
