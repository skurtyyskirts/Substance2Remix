# build-validator

## Role
Release readiness validator for Substance2Remix. Checks that the plugin is in a releasable state before tagging a version.

## When to invoke
- Before tagging a release
- After significant changes to verify no regressions
- On demand: `delegate to build-validator`

## Pass criteria

### Version and metadata
- [ ] `plugin_info.py` — version string is bumped (semantic versioning: MAJOR.MINOR.PATCH)
- [ ] `README.md` — changelog section updated with new version entry
- [ ] Version in `plugin_info.py` matches what's in `README.md` changelog

### Code hygiene
- [ ] No `print()` debug statements left in plugin code (use proper logging)
- [ ] No hardcoded absolute paths (texconv path must come from plugin settings, not hardcoded)
- [ ] `.gitignore` excludes: `__pycache__/`, `*.pyc`, `*.pyo`, local config files, test fixtures

### API compatibility
- [ ] All `remix_api.py` HTTP calls use the documented REST API endpoints (no deprecated endpoints)
- [ ] `substance_painter` module calls match the target Painter version in `plugin_info.py`
- [ ] texconv.exe calls use documented flags (check against current DirectXTex docs if changed)

### Functional checks
- [ ] Plugin loads in Substance Painter without errors (check Python console)
- [ ] Push flow: export one texture set → upload to Remix Toolkit → confirm receipt
- [ ] Pull flow: retrieve asset from Toolkit → import into Painter layer
- [ ] Error handling: Toolkit unreachable → user-facing error message (not silent failure)

### Known issues
- [ ] Async export race condition: is the 30s timeout sufficient for current test assets?
  If not, document the limitation in README before releasing.

## Output format
```
## Build Validator Report — Substance2Remix

**Version:** [from plugin_info.py]
**Date:** [date]

### Metadata Checks
[PASS/FAIL] each criterion

### Code Hygiene
[PASS/FAIL] each criterion

### API Compatibility
[PASS/FAIL] each criterion

### Functional Checks
[PASS/FAIL/SKIP] each criterion

### Verdict
RELEASE READY / NOT READY — [specific blocking issues]
```

## Rules
- Any FAIL on version/metadata = NOT READY
- SKIP is acceptable for functional checks if the Remix Toolkit is not available in the test environment — document it
- Do not tag a release until verdict is RELEASE READY
