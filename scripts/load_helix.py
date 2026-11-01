import json
import os
import sys
import time
import urllib.error
import urllib.request

ORIGIN = os.environ.get("HELIX_ORIGIN", "http://localhost:3001").rstrip("/")
API = ORIGIN + "/api/v1"
WORKSPACE_NAME = "AI code judgments"
DATASET = "pull_requests"


def request(method, path, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise SystemExit(f"{method} {path} returned HTTP {error.code}:\n{detail}")


def load_rows(paths):
    rows = []
    for path in paths:
        rows.append(json.load(open(path, encoding="utf-8")))
    if not rows:
        raise SystemExit("Give one or more judgment JSON files.")
    return collapse(rows)


def collapse(rows):
    grouped = {}
    for row in rows:
        key = (row.get("repository"), row.get("pull_request"))
        slot = grouped.setdefault(key, {})
        merge_only = row.get("event") == "merged" or (
            row.get("merged") and row.get("ai_generated") is None
        )
        if merge_only:
            slot["merge"] = row
        else:
            previous = slot.get("judge")
            if previous is None or (row.get("judged_at") or "") >= (
                previous.get("judged_at") or ""
            ):
                slot["judge"] = row
    combined = []
    for slot in grouped.values():
        base = dict(slot.get("judge") or slot.get("merge") or {})
        merge = slot.get("merge")
        if merge:
            base["merged"] = True
            base["merged_at"] = merge.get("merged_at")
            base["merge_commit_sha"] = merge.get("merge_commit_sha")
            base["updated_at"] = merge.get("updated_at") or base.get("updated_at")
            base["event"] = "merged"
        combined.append(base)
    return combined


def workspace_id():
    me = request("GET", "/me")
    for workspace in me.get("workspaces") or []:
        if workspace.get("name") == WORKSPACE_NAME:
            return workspace["id"]
    created = request("POST", "/workspaces", {"name": WORKSPACE_NAME})
    return created["id"]


def dataset_id(workspace):
    listed = request("GET", f"/workspaces/{workspace}/resources/dataset?limit=100")
    for item in listed.get("items") or []:
        if item.get("name") == DATASET:
            return item["id"]
    return None


def ingest(workspace, rows):
    existing = dataset_id(workspace)
    body = {"name": DATASET, "rows": rows}
    if existing:
        body["datasetId"] = existing
    saved = request("POST", f"/workspaces/{workspace}/ingest", body)
    return saved["id"]


def ensure_published(workspace):
    state = request("GET", f"/workspaces/{workspace}/onboarding")
    if state.get("complete"):
        return
    request(
        "POST",
        f"/workspaces/{workspace}/onboarding/provider",
        {"provider": "local", "model": "qwen3:4b", "advanceToData": True},
    )
    state = request("POST", f"/workspaces/{workspace}/onboarding/ontology", {})
    ontology = state.get("ontology") or {}
    if not ontology.get("hash"):
        raise SystemExit("Helix did not return an ontology suggestion.")
    request(
        "POST",
        f"/workspaces/{workspace}/onboarding/ontology/confirm",
        {"hash": ontology["hash"]},
    )
    for _ in range(90):
        state = request("GET", f"/workspaces/{workspace}/onboarding")
        if state.get("complete"):
            return
        time.sleep(5)
    run = state.get("buildRun") or {}
    raise SystemExit(
        "The workspace was not published. Build status: "
        f"{run.get('data', {}).get('status')} {run.get('data', {}).get('stage')}"
    )


def save_board(workspace, dataset):
    def widget(title, why, kind, sql, format="number"):
        return {
            "title": title,
            "why": why,
            "kind": kind,
            "format": format,
            "source": DATASET,
            "sql": sql,
            "inputs": [dataset],
        }

    board = request(
        "PUT",
        f"/workspaces/{workspace}/home/board",
        {
            "name": "AI code judgments",
            "widgets": [
                widget(
                    "Pull requests judged",
                    "One row is one pull request diff. A merge does not add a second row.",
                    "kpi",
                    f"SELECT COUNT(*) AS value FROM {DATASET}",
                ),
                widget(
                    "Marked AI",
                    "The model marked the pull request diff. This is not a line count of agent code.",
                    "kpi",
                    f"SELECT SUM(CASE WHEN ai_generated THEN 1 ELSE 0 END) AS value FROM {DATASET}",
                ),
                widget(
                    "Share marked AI",
                    "Pull requests the model marked, out of every judged pull request.",
                    "kpi",
                    f"SELECT 100.0 * SUM(CASE WHEN ai_generated THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS value FROM {DATASET}",
                    "percent",
                ),
                widget(
                    "Lines added on marked AI",
                    "Lines GitHub counted on pull requests the model marked.",
                    "kpi",
                    f"SELECT COALESCE(SUM(CASE WHEN ai_generated THEN additions ELSE 0 END), 0) AS value FROM {DATASET}",
                ),
                widget(
                    "Mark",
                    "Marked AI, not marked AI, or not judged.",
                    "breakdown",
                    f"SELECT mark AS label, COUNT(*) AS value FROM {DATASET} GROUP BY mark",
                ),
                widget(
                    "Lines added by author",
                    "GitHub line counts for the person who opened the pull request.",
                    "breakdown",
                    f"SELECT author_login AS label, COALESCE(SUM(additions), 0) AS value FROM {DATASET} GROUP BY author_login",
                ),
            ],
        },
    )
    errors = [
        f"{item.get('title')}: {item.get('result', {}).get('error')}"
        for item in board.get("widgets") or []
        if item.get("result", {}).get("error")
    ]
    if errors:
        raise SystemExit("Home board query failed:\n" + "\n".join(errors))
    return board


def main():
    paths = sys.argv[1:]
    if not paths:
        if os.path.exists("judgment.json"):
            paths = ["judgment.json"]
        else:
            raise SystemExit("Usage: python3 scripts/load_helix.py judgment.json")
    rows = load_rows(paths)
    workspace = workspace_id()
    dataset = ingest(workspace, rows)
    ensure_published(workspace)
    board = save_board(workspace, dataset)
    print(
        json.dumps(
            {
                "workspace": workspace,
                "dataset": dataset,
                "rows": len(rows),
                "widgets": [item.get("title") for item in board.get("widgets") or []],
                "url": ORIGIN + "/",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
