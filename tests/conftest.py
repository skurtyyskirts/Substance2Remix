"""Shared test setup: installs lightweight stubs for the optional `requests`
dependency and Substance Painter API surfaces touched at module import time.

Without this, tests that import core (which transitively imports remix_api)
would either fail on missing `requests` or trip on substance_painter imports.
Putting the stubs here ensures a single canonical stub is installed before any
test module is collected, so exception classes referenced by remix_api match
the ones tests raise.

Run the suite with Painter's own interpreter so PySide6 and the vendored
Pillow binary match (see CLAUDE.md).
"""
import os
import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    _req_mock = MagicMock()
    _RequestException = type("RequestException", (OSError,), {})
    _req_mock.exceptions.RequestException = _RequestException
    _req_mock.exceptions.ConnectionError = type("ConnectionError", (_RequestException,), {})
    _req_mock.exceptions.Timeout = type("Timeout", (_RequestException,), {})
    sys.modules["requests"] = _req_mock

for _mod in (
    "substance_painter",
    "substance_painter.logging",
    "substance_painter.ui",
    "substance_painter.project",
    "substance_painter.resource",
    "substance_painter.textureset",
    "substance_painter.export",
    "substance_painter.layerstack",
    "substance_painter.event",
    "substance_painter.application",
):
    sys.modules.setdefault(_mod, MagicMock())

# The vendored Pillow (texture_processor normal-map tests). requests is
# already stubbed above, so only PIL is picked up from here.
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.append(_VENDOR)
