#!/usr/bin/env python3
"""
Parse CHANGELOG.md for TombRaiderUnderworldRTX.
Extracts build entries as structured dicts for use by sync.py and GitHub Actions.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def parse_changelog(text: str) -> list:
    """
    Returns list of dicts: {title, build_number, status, patches, notes, raw}
    Expects entries separated by '## ' headings.
    """
    entries = []
    sections = re.split(r"\n(?=## )", text.strip())
    for section in sections:
        if not section.startswith("## ") and not section.startswith("# "):
            continue
        lines = section.strip().splitlines()
        title_line = lines[0].lstrip("# ").strip()
        body = "\n".join(lines[1:]).strip()

        build_match = re.search(r"[Bb]uild\s*#?(\d+)", title_line)
        build_number = int(build_match.group(1)) if build_match else None

        status_match = re.search(r"\[(PASS|FAIL|PARTIAL|WIP)\]", title_line, re.IGNORECASE)
        status = status_match.group(1).upper() if status_match else "UNKNOWN"

        patch_matches = re.findall(r"- Patch[^:]*:\s*(.+)", body)

        entries.append(
            {
                "title": title_line,
                "build_number": build_number,
                "status": status,
                "patches": patch_matches,
                "notes": body,
                "raw": section,
            }
        )
    return entries


def last_n_entries(n: int = 20) -> list:
    path = ROOT / "CHANGELOG.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries = parse_changelog(text)
    return entries[-n:]


def format_for_context(entries: list) -> str:
    """Format entries as a compact context block for the idea-generation workflow."""
    lines = []
    for e in entries:
        lines.append(f"### {e['title']}")
        if e["patches"]:
            lines.append("Patches: " + ", ".join(e["patches"]))
        if e["notes"]:
            # Truncate long notes
            notes = e["notes"][:400] + "..." if len(e["notes"]) > 400 else e["notes"]
            lines.append(notes)
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    entries = last_n_entries(n)
    print(format_for_context(entries))
