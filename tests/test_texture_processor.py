"""Tests for texture_processor.py DDS pipeline."""
import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from texture_processor import TextureProcessor, TEXCONV_TIMEOUT_SECONDS, BLENDER_TIMEOUT_SECONDS


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


class TestStripKnownTextureExtensions(unittest.TestCase):
    def test_strips_dds(self):
        self.assertEqual(TextureProcessor._strip_known_texture_extensions("foo.dds"), "foo")

    def test_strips_rtex_dds(self):
        self.assertEqual(TextureProcessor._strip_known_texture_extensions("foo.rtex.dds"), "foo")

    def test_strips_png(self):
        self.assertEqual(TextureProcessor._strip_known_texture_extensions("bar.png"), "bar")

    def test_handles_windows_path(self):
        result = TextureProcessor._strip_known_texture_extensions(r"C:\textures\foo.dds")
        self.assertEqual(result, "foo")


class TestStripIngestChannelSuffix(unittest.TestCase):
    def test_strips_single_letter_suffixes(self):
        for letter in "anrmheo":
            self.assertEqual(
                TextureProcessor._strip_ingest_channel_suffix(f"foo.{letter}"),
                "foo",
                msg=f"expected suffix .{letter} to be stripped",
            )

    def test_leaves_no_suffix(self):
        self.assertEqual(TextureProcessor._strip_ingest_channel_suffix("foo"), "foo")

    def test_leaves_multi_char_suffix(self):
        self.assertEqual(TextureProcessor._strip_ingest_channel_suffix("foo.ab"), "foo.ab")


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



class TestSafeBasename(unittest.TestCase):
    def test_none_returns_empty_string(self):
        self.assertEqual(TextureProcessor.safe_basename(None), "")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(TextureProcessor.safe_basename(""), "")

    def test_forward_slashes(self):
        self.assertEqual(TextureProcessor.safe_basename("some/path/file.dds"), "file.dds")

    def test_backslashes(self):
        self.assertEqual(TextureProcessor.safe_basename("some\\path\\file.dds"), "file.dds")

    def test_mixed_slashes(self):
        self.assertEqual(TextureProcessor.safe_basename("some/mixed\\path/file.dds"), "file.dds")

    def test_no_slashes(self):
        self.assertEqual(TextureProcessor.safe_basename("file.dds"), "file.dds")

    def test_non_string_object(self):
        import pathlib
        path = pathlib.Path("some/path/file.dds")
        self.assertEqual(TextureProcessor.safe_basename(path), "file.dds")

    @patch("ntpath.basename")
    def test_exception_fallback(self, mock_basename):
        mock_basename.side_effect = Exception("Test exception")
        self.assertEqual(TextureProcessor.safe_basename("some/path/file.dds"), "some/path/file.dds")


if __name__ == "__main__":
    unittest.main()
