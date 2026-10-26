"""Settings and named presets, saved as JSON in the user's config folder.

Every change is written immediately (settings.json), and presets live next to
it (presets.json). The folder is outside the plugin, so reinstalling or
updating the plugin keeps both. A settings.json left in the plugin folder by
earlier versions is migrated on first load.
"""
import json
import os
import shutil

from .settings_schema import (
    PRESET_KEYS, atomic_write_json, preset_values, sanitize_settings, user_config_dir,
)

SETTINGS_FILE_NAME = "settings.json"
PRESETS_FILE_NAME = "presets.json"
PRESETS_VERSION = 1


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
        self.presets_path = os.path.join(self.config_dir, PRESETS_FILE_NAME)
        self.legacy_settings_path = legacy_settings_path
        self.settings = {}
        self.presets = {}
        # Problems from the last load/save, for the caller to log.
        self.errors = []
        # presets.json existed but couldn't be read (locked, corrupt): merge it back before writing.
        self._presets_unread = False
        self._deleted_presets = set()

    # --- Settings ---

    def load(self):
        """Read settings and presets. Returns the sanitized settings."""
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

        self.presets, err = self._read_presets()
        self._presets_unread = bool(err)
        if err:
            backup = _backup(self.presets_path)
            self.errors.append(f"Presets unreadable ({err})" + (f"; the old file is kept as {backup}" if backup else ""))
        if self.settings.get("active_preset") not in self.presets:
            self.settings["active_preset"] = ""

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
        """Factory settings. Presets are kept, but none is active afterwards."""
        self.settings = sanitize_settings({}, self.plugin_dir)
        self.save()
        return self.settings

    # --- Presets ---

    def _clean_preset(self, values):
        """Only preset keys, with the values sanitize_settings would produce."""
        known = {k: v for k, v in (values or {}).items() if k in PRESET_KEYS}
        return preset_values(sanitize_settings(known, self.plugin_dir))

    def _read_presets(self):
        data, err = _read_json(self.presets_path)
        presets = data.get("presets") if isinstance(data.get("presets"), dict) else {}
        return {str(name): self._clean_preset(values) for name, values in presets.items()
                if str(name).strip() and isinstance(values, dict)}, err

    def _save_presets(self):
        if self._presets_unread:
            # Never replace presets we couldn't read at startup; merge them back in first.
            on_disk, err = self._read_presets()
            if not err:
                self._presets_unread = False
                for name, values in on_disk.items():
                    if name not in self.presets and name not in self._deleted_presets:
                        self.presets[name] = values
        ok, err = atomic_write_json(self.presets_path, {"version": PRESETS_VERSION, "presets": self.presets})
        if not ok:
            self.errors.append(f"Could not save presets to {self.presets_path}: {err}")
        return ok

    def preset_names(self):
        return sorted(self.presets, key=str.lower)

    @property
    def active_preset(self):
        name = self.settings.get("active_preset") or ""
        return name if name in self.presets else ""

    def is_modified(self):
        """True when the settings differ from the active preset."""
        name = self.active_preset
        return bool(name) and preset_values(self.settings) != self.presets[name]

    def save_preset(self, name):
        """Store the current workflow settings under ``name`` and make it active."""
        name = str(name or "").strip()
        if not name:
            raise ValueError("A preset needs a name.")
        self.presets[name] = self._clean_preset(self.settings)
        self._save_presets()
        return self.update({"active_preset": name})

    def apply_preset(self, name):
        """Load a preset into the settings. Returns the new settings."""
        if name not in self.presets:
            raise KeyError(f"No preset named '{name}'.")
        return self.update({**self.presets[name], "active_preset": name})

    def delete_preset(self, name):
        if self.presets.pop(name, None) is None:
            return self.settings
        self._deleted_presets.add(name)
        self._save_presets()
        if self.settings.get("active_preset") == name:
            return self.update({"active_preset": ""})
        return self.settings
