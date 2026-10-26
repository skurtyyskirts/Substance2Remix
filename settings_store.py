"""Plugin settings, saved as JSON in the user's config folder.

Every change is written immediately (settings.json) and loaded again on the
next start. The folder is outside the plugin, so reinstalling or updating the
plugin keeps the settings. A settings.json left in the plugin folder by
earlier versions is migrated on first load.
"""
import json
import os
import shutil

from .settings_schema import atomic_write_json, sanitize_settings, user_config_dir

SETTINGS_FILE_NAME = "settings.json"


def _read_json(path):
    """(dict, error). A missing file is not an error."""
    if not path or not os.path.isfile(path):
        return {}, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data if isinstance(data, dict) else {}), None
    except Exception as e:
        return {}, f"{path}: {e}"


def _backup(path):
    """Keep an unreadable file as <path>.bak before anything overwrites it."""
    try:
        shutil.copy2(path, f"{path}.bak")
        return f"{path}.bak"
    except Exception:
        return None


class SettingsStore:
    def __init__(self, plugin_dir, config_dir=None, legacy_settings_path=None):
        self.plugin_dir = plugin_dir
        self.config_dir = config_dir or user_config_dir()
        self.settings_path = os.path.join(self.config_dir, SETTINGS_FILE_NAME)
        self.legacy_settings_path = legacy_settings_path
        self.settings = {}
        # Problems from the last load/save, for the caller to log.
        self.errors = []

    def load(self):
        """Read the settings. Returns the sanitized settings."""
        self.errors = []
        raw, err = _read_json(self.settings_path)
        migrated = False
        if err:
            backup = _backup(self.settings_path)
            self.errors.append(f"Settings unreadable, using defaults ({err})"
                               + (f"; the old file is kept as {backup}" if backup else ""))
        elif not os.path.isfile(self.settings_path) and self.legacy_settings_path and os.path.isfile(self.legacy_settings_path):
            raw, err = _read_json(self.legacy_settings_path)
            if err:
                self.errors.append(f"Old settings unreadable ({err})")
            migrated = bool(raw)
        self.settings = sanitize_settings(raw, self.plugin_dir)
        if migrated:
            self.save()
        return self.settings

    def save(self):
        ok, err = atomic_write_json(self.settings_path, self.settings)
        if not ok:
            self.errors.append(f"Could not save settings to {self.settings_path}: {err}")
        return ok

    def update(self, values):
        """Merge ``values`` into the settings, sanitize and save. Returns the new
        settings dict (a new object, so readers on other threads keep a
        consistent snapshot)."""
        merged = dict(self.settings)
        merged.update(values or {})
        self.settings = sanitize_settings(merged, self.plugin_dir)
        self.save()
        return self.settings

    def reset_to_defaults(self):
        """Factory settings, saved."""
        self.settings = sanitize_settings({}, self.plugin_dir)
        self.save()
        return self.settings
