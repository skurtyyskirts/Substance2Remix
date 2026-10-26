"""Load a plugin module with some of its sibling modules replaced by fakes.

Each call builds a fresh throwaway package whose __path__ is the plugin
folder, so relative imports (``from .qt_utils import ...``) resolve to the
fakes registered in sys.modules. This avoids patching builtins.__import__,
which breaks once PySide6 installs its own import hook.
"""
import importlib
import itertools
import os
import sys
import types

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_counter = itertools.count()


def load_isolated(module_name, **fake_siblings):
    pkg_name = f"_s2r_isolated_{next(_counter)}"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [PLUGIN_DIR]
    sys.modules[pkg_name] = pkg
    for name, module in fake_siblings.items():
        sys.modules[f"{pkg_name}.{name}"] = module
    return importlib.import_module(f"{pkg_name}.{module_name}")
