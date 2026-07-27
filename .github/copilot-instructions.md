# Copilot Instructions — Substance2Remix

A **Substance 3D Painter plugin** (Python) that bridges Adobe Substance Painter with the **NVIDIA RTX Remix Toolkit** — pull a mesh + textures from Remix, paint, push textures back. No build step: the plugin folder is copied into Painter's `python/plugins/`.

## Read first
- `CLAUDE.md` — module map, key entry points, network/TLS policy, texconv pipeline, pending PRs. Then `README.md` for user-facing behavior.

## Module map
- `__init__.py` → loads `core.py` (`RemixConnectorPlugin`, central orchestration).
- `remix_api.py` — REST client for the Remix Toolkit (`RemixAPIClient`).
- `texture_processor.py` — DDS pipeline (texconv) + Blender unwrap.
- `painter_controller.py` — Substance Painter API wrapper. `async_utils.py` — Qt worker threads. `dependency_manager.py` — loads `_vendor/`.
- UI: `settings_dialog.py`, `diagnostics_dialog.py`, `qt_utils.py`, `settings_schema.py`.

## Don't break these invariants
- **The Remix round-trip:** `pull_from_remix()` → paint → `push_to_remix()` / `force_push_to_remix()` (relink to a new material hash) / `import_textures_from_remix()`. Keep the `ingest_texture` → `update_textures_batch` → `save_layer` chain intact.
- **All HTTP goes through `RemixAPIClient.make_request()`** — never add bare `requests.get/post`. It owns retry logic and the TLS policy: `verify=False` only when the host is `localhost` / `127.0.0.1` / `[::1]` (substring match — `https://localhost.evil.com` also matches; tighten host parsing before exposing to untrusted input), `verify=True` otherwise.
- **Guard Substance Painter / Qt usage behind the existing `QT_AVAILABLE` checks** so headless CI tests keep importing.
- **texconv** is shelled out with a hard 180 s timeout (`TEXCONV_TIMEOUT_SECONDS`); Blender unwrap 900 s (`BLENDER_TIMEOUT_SECONDS`). Keep the timeouts.

## Testing & docs
- No build step. Run tests: `python -m pytest tests/` (Linux + Qt-guarded in CI). Run anything you touch before claiming completion.
- Update `CHANGELOG.md` for notable changes and keep `CLAUDE.md` "Current State" / "Known Issues" current. Two PRs are pending review (see `CLAUDE.md`) — coordinate, don't duplicate.

## Conventions
- Match the file's style; keep functions small and single-purpose; type hints over type comments; Google-style docstrings on public methods.
- Never commit secrets, API keys, or vendored binaries you didn't intend to.

## Scoped guidance, agents & prompts
- Python/Qt work → `.github/instructions/python.instructions.md`. Remix REST + texture pipeline → `.github/instructions/remix-api.instructions.md`.
- Upstream/API monitoring → the **research-scanner** agent; Painter API drift → **painter-api-compat-monitor**; session-end doc + Linear sync → **doc-sync** (`.github/agents/`).
- Reusable workflows in `.github/prompts/`: `/add-feature`, `/run-tests`, `/review-pr`, `/triage-issue`.
