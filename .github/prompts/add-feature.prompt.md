---
mode: agent
description: Implement a Substance2Remix feature with a WBC parity check, tests, and changelog.
---

Implement a feature in the Substance2Remix plugin. Feature: ${input:feature:What to add or change}

1. **Orient** — read `CLAUDE.md` (module map, invariants, pending PRs) and `docs/wbc_parity_audit.md` (WholeBodyCapture is the reference plugin; check whether an equivalent already exists before building new).
2. **Place the change correctly** — orchestration in `core.py`; all HTTP through `RemixAPIClient.make_request()` in `remix_api.py`; texture/DDS work in `texture_processor.py`; background work in `async_utils.py` (never block the UI thread). Guard Painter/Qt behind `QT_AVAILABLE`.
3. **Preserve invariants** — the Remix round-trip (`ingest_texture` → `update_textures_batch` → `save_layer`), the TLS policy in `make_request()`, and the texconv/Blender timeouts.
4. **Tests** — add or adjust under `tests/`; run `python -m pytest tests/` (headless, Qt-guarded).
5. **Docs** — update `CHANGELOG.md` and `CLAUDE.md` "Current State"; update `docs/wbc_parity_audit.md` if parity changed. Keep the diff minimal and report what changed + test results.
