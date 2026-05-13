#!/usr/bin/env python3
"""
Linear setup for Substance2Remix.
Registers Substance2RemixRTX as a project under the shared 'RTX Remix Plugins' team.
"""

import os, json, urllib.request
from pathlib import Path

API_URL = "https://api.linear.app/graphql"
API_KEY = os.environ.get("LINEAR_API_KEY", "")

TEAM_NAME = "RTX Remix Game Ports"
PROJECT_NAME = "Substance2RemixRTX"

LABELS = [
    "push", "pull", "auth", "textures", "blender-unwrap",
    "api-compat", "upstream", "auto-idea",
]

INITIAL_ISSUES = [
    {
        "title": "Fix async export race condition in texture upload flow",
        "description": (
            "painter_controller.py exports textures asynchronously. "
            "remix_api.py polls for completion but times out after 30s. "
            "Fix: use Substance Painter export callback or increase timeout with exponential backoff."
        ),
        "label": "textures",
        "priority": 1,
    },
    {
        "title": "Validate texconv.exe path at plugin startup",
        "description": (
            "Plugin silently fails on texture conversion if texconv.exe is missing. "
            "Add startup validation: check path exists, show user-facing error if not. "
            "Default: C:\\Users\\skurtyy\\AppData\\Local\\Temp\\texconv.exe"
        ),
        "label": "textures",
        "priority": 1,
    },
    {
        "title": "Implement missing texture channel support",
        "description": (
            "Audit which PBR channels are currently supported (albedo, roughness, metalness, normal, emissive) "
            "and which are missing. RTX Remix supports additional channels — map them."
        ),
        "label": "push",
        "priority": 2,
    },
    {
        "title": "Add batch export for multiple assets",
        "description": "Currently exports one asset at a time. Add batch mode: export all modified assets in one operation.",
        "label": "push",
        "priority": 2,
    },
    {
        "title": "Make Blender auto-unwrap async (non-blocking)",
        "description": (
            "Blender subprocess call blocks the Painter UI. "
            "Move to a background thread with progress indicator."
        ),
        "label": "blender-unwrap",
        "priority": 2,
    },
    {
        "title": "Activate Linear sync for Substance2Remix",
        "description": "Run setup_linear.py, commit config.json, enable workflows.",
        "label": "api-compat",
        "priority": 3,
    },
]


def gql(query, variables=None):
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API_URL, data=payload,
        headers={"Content-Type": "application/json", "Authorization": API_KEY})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get_or_create_team():
    for t in gql("{ teams { nodes { id name } } }")["data"]["teams"]["nodes"]:
        if t["name"] == TEAM_NAME:
            return t["id"]
    return gql("mutation($n: String!) { teamCreate(input: {name: $n}) { team { id } } }", {"n": TEAM_NAME})["data"]["teamCreate"]["team"]["id"]


def get_or_create_project(team_id):
    for p in gql("{ projects { nodes { id name } } }")["data"]["projects"]["nodes"]:
        if p["name"] == PROJECT_NAME:
            return p["id"]
    return gql("mutation($n: String!, $t: [String!]!) { projectCreate(input: {name: $n, teamIds: $t}) { project { id } } }",
               {"n": PROJECT_NAME, "t": [team_id]})["data"]["projectCreate"]["project"]["id"]


def get_or_create_labels(team_id):
    existing = {l["name"].lower(): l["id"] for l in gql(
        "query($t: String!) { team(id: $t) { labels { nodes { id name } } } }",
        {"t": team_id})["data"]["team"]["labels"]["nodes"]}
    ids = {}
    for name in LABELS:
        if name.lower() in existing:
            ids[name] = existing[name.lower()]
        else:
            ids[name] = gql("mutation($n: String!, $t: String!) { issueLabelCreate(input: {name: $n, teamId: $t}) { issueLabel { id } } }",
                            {"n": name, "t": team_id})["data"]["issueLabelCreate"]["issueLabel"]["id"]
    return ids


def main():
    if not API_KEY:
        raise SystemExit("ERROR: LINEAR_API_KEY not set.")
    print("=== Substance2Remix Linear Setup ===")
    team_id = get_or_create_team(); print(f"Team: {team_id}")
    project_id = get_or_create_project(team_id); print(f"Project: {project_id}")
    label_ids = get_or_create_labels(team_id)
    states = {s["name"]: s["id"] for s in gql(
        "query($t: String!) { team(id: $t) { states { nodes { id name } } } }",
        {"t": team_id})["data"]["team"]["states"]["nodes"]}
    for issue in INITIAL_ISSUES:
        lid = label_ids.get(issue["label"])
        gql("""mutation($t: String!, $p: String!, $ti: String!, $d: String!, $pr: Int!, $l: [String!]) {
            issueCreate(input: {teamId: $t, projectId: $p, title: $ti, description: $d, priority: $pr, labelIds: $l}) { success }
        }""", {"t": team_id, "p": project_id, "ti": issue["title"], "d": issue["description"],
               "pr": issue["priority"], "l": [lid] if lid else []})
        print(f"  Issue: {issue['title'][:80]}")
    config = {"teamId": team_id, "teamName": TEAM_NAME, "projectId": project_id,
              "projectName": PROJECT_NAME, "labelIds": label_ids, "workflowStates": states}
    (Path(__file__).parent / "config.json").write_text(json.dumps(config, indent=2))
    print("Done.")

if __name__ == "__main__":
    main()
