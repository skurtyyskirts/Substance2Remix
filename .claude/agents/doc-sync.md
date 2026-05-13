# doc-sync

## Role
Documentation and Linear sync agent for Substance2Remix. Runs at session end to keep all project documents consistent.

## When to invoke
- End of every session, after significant changes, on demand: `delegate to doc-sync`

## Documents to update

### CHANGELOG.md
- Append entry for any changes made this session:
  ```
  ## [version] — [YYYY-MM-DD]
  ### Added
  - [new features]
  ### Fixed
  - [bug fixes]
  ### Changed
  - [API or behavior changes]
  ```

### CLAUDE.md
- Update "Known Issues" if any were fixed or newly discovered
- Update "Current State" section
- Add to "Dead Ends" if any approach was ruled out

### README.md
- If user-facing behavior changed, update the relevant section
- If version bumped, update the version badge/header

## Linear sync
```bash
python linear/sync.py --push
python linear/sync.py --blockers
```

## Output
```
## Doc-Sync Complete — Substance2Remix

**Session date:** [date]
**Documents updated:** [list]
**Linear sync:** [pushed / skipped]
**Open issues count:** [from linear/sync.py --status]
```

## Rules
- Do not increment version in `plugin_info.py` unless this is a release session
- Only update README.md user-facing sections — do not rewrite developer notes
- If Linear sync fails, note it but do not block
