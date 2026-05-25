# Repository Health Check — 2026-05-20

Automated repo health check and aggressive cleanup pass for `skurtyyskirts/Substance2Remix`.

## Summary

| Metric | Before | After |
|---|---|---|
| Open PRs | 88 | 47 |
| Open issues | 0 | 0 |
| PRs merged | — | 1 |
| PRs closed (superseded / stale) | — | 40 |

## PR Audit

### Authorship / Source

Every open PR is attributed to the repo owner `skurtyyskirts`, but the actual sources (inferred from branch prefixes) are:

- `jules-*`, `jules/*`, and clean-slug branches (`add-*-tests-*`, `fix-*-*`, `clean-*-*`, `code-health/*`, `perf/*`, `test-*-*`) — Jules bot
- `claude/*` — Claude Code agent
- `cursor/*` — Cursor background agent (PR #1 only)

No PRs from `dependabot[bot]` are currently open.

### CI Posture (critical finding)

The repo currently has **no real test/lint CI on PRs**. The four workflow files are:

- `.github/workflows/api-compat-check.yml` — weekly scheduled API snapshot check, gated by `vars.LINEAR_ENABLED`
- `.github/workflows/github-linear-sync.yml` — informational sync only, runs on issue/PR events
- `.github/workflows/idea-generation.yml` — weekly scheduled, gated by `vars.LINEAR_ENABLED`
- `.github/workflows/linear-sync.yml` — runs only on pushes to `main` touching `CHANGELOG.md` / `TEST_STATUS.md`

For PR events, only `sync-to-linear` runs and it is informational. There is **no pytest, ruff, mypy, or CodeQL workflow attached to PRs**. PR #79 attempted to add `python-tests.yml` (matrix 3.11/3.12) plus CodeQL and other reusable workflows, but failed (`pytest (3.11)`, `pytest (3.12)`, `risk`, `propose-pr` all failed) and is now conflicted; it was closed in this pass.

Because "green CI" is effectively only a Linear-sync ping for most PRs, this pass intentionally restricted **code merges** and only merged a 4-line workflow fix (PR #107). Aggressive merging of plugin-code PRs without a pytest workflow in place is unsafe per the safety policy on `remix_api.py` / `painter_helper.py` (now `painter_controller.py`).

### Actions Taken

**Merged (squash) — 1 PR**

- #107 — Fix failed workflows: `GH_TOKEN` and `linear-sync deps`. 4 added lines, two `.github/workflows/*.yml` files, `mergeable_state: clean`. Workflow-only fix, no plugin-code impact.

**Closed as superseded — 38 PRs** (newest PR in each cluster kept)

| Kept | Closed (older/duplicate) | Topic |
|---|---|---|
| #51 | #29, #30, #40, #50 | tests for `get_material_textures` |
| #101 | #49, #52, #57 | subprocess execution hardening / refactor |
| #33 | #7, #11, #20 | tests for `_force_push_root_conflicts` |
| #98 | #48, #97 | tests for `settings_schema.py` |
| #83 | #5, #14, #80 | remove unused `sys` import in `painter_controller.py` |
| #60 | #44, #54 | tests for `update_textures_batch` |
| #53 | #16, #17 | remove unused `_strip_known_texture_extensions` |
| #37 | #8, #28 | remove unused `_strip_ingest_channel_suffix` |
| #108 | #63 | refactor `make_request` |
| #99 | #91 | remove unused imports in `core.py` |
| #93 | #84, #86 | error tests for `load_settings` in `core.py` |
| #55 | #32 | tests for `ingest_texture` |
| #42 | #38 | error-path test for `derive_project_name_from_dir` |
| #35 | #12 | remove unused `create_project` method |
| #31 | #18, #19 | tests for texture-assignment fallback |
| #15 | #6 | remove unused `sys` import in `qt_utils.py` |
| #26 | #22 | remove unused `sys` import in `remix_api.py` |
| #105 | #104 | enable GitHub Pro automation pack |
| #94 | #88 | remove unused `PIL` (and `requests`) imports |
| #102 | #100 | unblock `time.sleep` with interruptible event |
| #59 | #34, #45, #56 | optimize filename-conflict / `choose_non_overwriting_root` I/O |

**Closed as stale — 2 PRs**

- #1 — 292 days old, no activity since 2025-08-09, `mergeable_state: dirty`, touches sensitive plugin logic that has evolved significantly. Cursor background agent PR.
- #79 — 13 days old but with 4 failing checks (`pytest 3.11`, `pytest 3.12`, `risk`, `propose-pr`) and `mergeable_state: dirty`. The reusable-workflow approach it introduced has not landed; PR #107 used a smaller targeted fix for the same workflow issues.

### Remaining Open PRs (47)

After cleanup the open queue is the de-duplicated set listed below. None were merged because (a) no real pytest CI gate is in place and (b) most touch the sensitive modules `remix_api.py`, `painter_controller.py`, `core.py`, `dependency_manager.py`, `texture_processor.py`, or `qt_utils.py`. Recommend landing a `python-tests.yml` (smaller than PR #79's attempt) before continuing.

Code-health / unused-imports: #13, #15, #23, #26, #35, #37, #53, #64, #83, #87, #89, #90, #94, #99, #103
Tests: #9, #27, #31, #33, #36, #41, #42, #47, #51, #55, #58, #60, #61, #62, #71, #72, #73, #76, #77, #82, #93, #98
Performance: #59, #81, #85, #92, #96, #102
Security: #95 (TLS verification bypass via absolute URL — touches `remix_api.py`, needs careful review)
Refactors: #101 (subprocess), #108 (`make_request`)
Repo automation: #105 (GitHub Pro automation pack)

## Issues

`mcp__github__list_issues` reports `totalCount: 0`. No open issues at audit time.

## Workflow Health

| File | Status | Notes |
|---|---|---|
| `api-compat-check.yml` | OK | Weekly cron + manual dispatch. Conditional on `vars.LINEAR_ENABLED == 'true'`. |
| `github-linear-sync.yml` | OK | Runs the `sync-to-linear` check on every PR/issue event — this is the green "success" most PRs are showing. |
| `idea-generation.yml` | Fixed via #107 | Was missing `GH_TOKEN` env for `gh pr create`; merged today. |
| `linear-sync.yml` | Fixed via #107 | Was missing `pip install requests`; merged today. |

**Recommendations**

1. Add `python-tests.yml` (pytest matrix on 3.11 + 3.12) — currently the repo has a `tests/` directory but no PR-gating CI executes it.
2. Add `ruff`/`pyflakes` workflow to validate the dozens of pending "remove unused import" PRs automatically.
3. Add `CodeQL` workflow for Python (PR #79 attempted this; reattempt as a smaller dedicated PR).
4. Configure branch protection on `main` requiring at least one green real CI check before merge — without this, the bot PR firehose will keep growing.
5. Configure dependabot (`.github/dependabot.yml` exists per HEAD commit `46ca0da`) to label its PRs `automerge` so the next health-check pass can auto-merge patch/minor bumps.

## Linear Sync

This repo maps to the Linear project **"Substance2Duplicate — AI Texturing Assistant"** (project id `d6d73eb6-c3d3-4f79-b4c4-ebfd55ee1a48`).

- Active high-priority issue: **SKU-116** — `NodeStack.from_textureset_stack`. No open GitHub PR currently targets it (no PR title/branch references `NodeStack`, `textureset_stack`, or `SKU-116`). Worth opening a tracking PR or sub-task.
- The `github-linear-sync.yml` workflow continues to run successfully on PR events, so PRs are being mirrored to Linear (search by `html_url`).
- After PR #107's merge, `linear-sync.yml` (on push to `main`) should now succeed when `CHANGELOG.md` is updated; verify on next CHANGELOG bump.

## Sensitive-File Touchpoints

PRs touching the sensitive surface `remix_api.py` / `painter_controller.py`:

- `remix_api.py`: #26, #51, #55, #60, #82, #85, #92, #95, #101, #108
- `painter_controller.py`: #9, #31, #35, #83

Per policy these may only be merged when (a) they are clearly trivial (e.g., remove single unused import) **and** (b) real CI is green. They are intentionally left open in this pass.

---

_Generated by automated repo health check 2026-05-20._
