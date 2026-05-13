#!/usr/bin/env python3
"""
Linear sync for Substance2Remix.
Reads CHANGELOG.md, CHANGELOG.md, and TEST_STATUS.md → pushes state to Linear.
Usage:
  python linear/sync.py --status     # print board summary
  python linear/sync.py --push       # push latest CHANGELOG entry as issue comment
  python linear/sync.py --blockers   # create/update blocker issues from WHITEBOARD
"""

import os
import sys
import json
import re
import urllib.request
from pathlib import Path

API_URL = "https://api.linear.app/graphql"
API_KEY = os.environ.get("LINEAR_API_KEY", "")
ROOT = Path(__file__).parent.parent
CONFIG_PATH = Path(__file__).parent / "config.json"


def gql(query: str, variables: dict = None):
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": API_KEY},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit("ERROR: linear/config.json not found. Run setup_linear.py first.")
    with open(CONFIG_PATH) as f:
        return json.load(f)


def read_file(name: str) -> str:
    p = ROOT / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def parse_last_changelog_entry(text: str) -> dict:
    """Extract the most recent build entry from CHANGELOG.md."""
    entries = re.split(r"\n## ", text)
    if len(entries) < 2:
        return {}
    last = entries[1]
    lines = last.strip().splitlines()
    title = lines[0].strip() if lines else "Unknown"
    body = "\n".join(lines[1:]).strip()
    return {"title": title, "body": body}


def parse_blockers(text: str) -> list:
    """Extract lines marked [BLOCKER] from CHANGELOG.md."""
    blockers = []
    for line in text.splitlines():
        if "[BLOCKER]" in line or "BLOCKER:" in line:
            blockers.append(line.strip("- #*").strip())
    return blockers


def cmd_status(config: dict):
    team_id = config["teamId"]
    project_id = config["projectId"]
    result = gql(
        """query($projectId: String!) {
            project(id: $projectId) {
                name
                issues { nodes { identifier title priority state { name } } }
            }
        }""",
        {"projectId": project_id},
    )
    project = result["data"]["project"]
    print(f"\n=== {project['name']} — Linear Board ===")
    issues = project["issues"]["nodes"]
    if not issues:
        print("  (no issues)")
        return
    by_state = {}
    for issue in issues:
        state = issue["state"]["name"]
        by_state.setdefault(state, []).append(issue)
    for state, items in by_state.items():
        print(f"\n  [{state}]")
        for i in items:
            prio = ["", "🔴", "🟠", "🟡", "🔵"][min(i["priority"], 4)]
            print(f"    {prio} {i['identifier']} — {i['title']}")


def cmd_push(config: dict):
    changelog = read_file("CHANGELOG.md")
    entry = parse_last_changelog_entry(changelog)
    if not entry:
        print("No CHANGELOG entries found.")
        return
    # Find or create a "Build Log" tracking issue
    result = gql(
        """query($teamId: String!, $title: String!) {
            issues(filter: {team: {id: {eq: $teamId}}, title: {contains: $title}}) {
                nodes { id identifier }
            }
        }""",
        {"teamId": config["teamId"], "title": "Build Log"},
    )
    issues = result["data"]["issues"]["nodes"]
    if issues:
        issue_id = issues[0]["id"]
        gql(
            "mutation($issueId: String!, $body: String!) { commentCreate(input: {issueId: $issueId, body: $body}) { success } }",
            {"issueId": issue_id, "body": f"**{entry['title']}**\n\n{entry['body']}"},
        )
        print(f"  Appended to build log issue.")
    else:
        gql(
            """mutation($teamId: String!, $projectId: String!, $title: String!, $description: String!) {
                issueCreate(input: {teamId: $teamId, projectId: $projectId, title: $title, description: $description}) {
                    issue { identifier }
                    success
                }
            }""",
            {
                "teamId": config["teamId"],
                "projectId": config["projectId"],
                "title": f"Build Log — {entry['title']}",
                "description": entry["body"],
            },
        )
        print(f"  Created build log issue.")


def cmd_blockers(config: dict):
    whiteboard = read_file("CHANGELOG.md")
    blockers = parse_blockers(whiteboard)
    if not blockers:
        print("No blockers found in CHANGELOG.md.")
        return
    label_id = config["labelIds"].get("api-compat") or config["labelIds"].get("proxy-code")
    for blocker in blockers:
        gql(
            """mutation($teamId: String!, $projectId: String!, $title: String!, $priority: Int!, $labelIds: [String!]) {
                issueCreate(input: {teamId: $teamId, projectId: $projectId, title: $title, priority: $priority, labelIds: $labelIds}) {
                    success
                }
            }""",
            {
                "teamId": config["teamId"],
                "projectId": config["projectId"],
                "title": f"[BLOCKER] {blocker}",
                "priority": 0,
                "labelIds": [label_id] if label_id else [],
            },
        )
        print(f"  Created blocker: {blocker}")


def main():
    if not API_KEY:
        raise SystemExit("ERROR: LINEAR_API_KEY not set.")
    config = load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if cmd == "--status":
        cmd_status(config)
    elif cmd == "--push":
        cmd_push(config)
    elif cmd == "--blockers":
        cmd_blockers(config)
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: sync.py [--status | --push | --blockers]")


if __name__ == "__main__":
    main()
