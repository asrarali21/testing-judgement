import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

ORIGIN = os.environ.get("HELIX_ORIGIN", "http://localhost:3001").rstrip("/")
API = ORIGIN + "/api/v1"
WORKSPACE_NAME = "Engineering performance POC"
PR_DATASET = "pull_requests"
DEVELOPER_DATASET = "developer_metrics"


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
        with open(path, encoding="utf-8") as handle:
            rows.append(json.load(handle))
    if not rows:
        raise SystemExit("Give one or more judgment JSON files.")
    return collapse(rows)


def number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def iso(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def lead_time_hours(row):
    if row.get("lead_time_hours") is not None:
        return number(row["lead_time_hours"], None)
    start, end = iso(row.get("created_at")), iso(row.get("merged_at"))
    if not start or not end:
        return None
    return round(max(0, (end - start).total_seconds() / 3600), 2)


def collapse(rows):
    grouped = {}
    for row in rows:
        key = (row.get("repository"), row.get("pull_request"))
        slot = grouped.setdefault(key, {})
        lifecycle_only = row.get("event") in {"merged", "closed"} or (
            row.get("merged") and row.get("ai_generated") is None
        )
        if lifecycle_only:
            previous = slot.get("lifecycle")
            if previous is None or (row.get("judged_at") or "") >= (
                previous.get("judged_at") or ""
            ):
                slot["lifecycle"] = row
        else:
            previous = slot.get("judge")
            if previous is None or (row.get("judged_at") or "") >= (
                previous.get("judged_at") or ""
            ):
                slot["judge"] = row
    combined = []
    for slot in grouped.values():
        lifecycle = slot.get("lifecycle")
        base = dict(slot.get("judge") or lifecycle or {})
        if lifecycle:
            # Keep the latest detector result, but refresh lifecycle, review and
            # CI evidence from the final closed/merged event.
            for field in (
                "merged",
                "merged_at",
                "merge_commit_sha",
                "updated_at",
                "event",
                "pr_state",
                "lead_time_hours",
                "review_comments",
                "approvals",
                "changes_requested",
                "review_iterations",
                "first_review_at",
                "first_review_response_hours",
                "commits_after_first_review",
                "workflow_runs",
                "workflow_failures",
                "workflow_cancelled",
                "ci_first_attempts",
                "ci_first_passes",
                "ci_first_pass_rate",
                "ci_recoveries",
            ):
                if field in lifecycle:
                    base[field] = lifecycle.get(field)
        if not base.get("pr_state"):
            base["pr_state"] = (
                "merged"
                if base.get("merged")
                else "closed"
                if base.get("event") == "closed"
                else "open"
            )
        # Gemini returns evidence as JSON for the workflow artifact. Store it
        # as one text field in the tabular Helix dataset so every PR remains
        # queryable without relying on array-column support.
        if isinstance(base.get("evidence"), list):
            base["evidence"] = " ".join(
                str(item).strip() for item in base["evidence"] if str(item).strip()
            ) or None
        # Older artifacts predate the Gemini assessment. Keep their schema
        # compatible with the new board and show them as not assessed.
        base.setdefault("assessment_status", "unavailable")
        base.setdefault("estimated_ai_assistance_pct", None)
        base.setdefault("evidence", None)
        base["lead_time_hours"] = lead_time_hours(base)
        base["has_review_rework"] = number(base.get("review_iterations")) > 0
        base["has_ci_failure"] = number(base.get("workflow_failures")) > 0
        combined.append(base)
    return sorted(
        combined,
        key=lambda row: (
            str(row.get("repository") or ""),
            number(row.get("pull_request")),
        ),
    )


def competency_level(evidence, strong, consistent):
    if evidence < 3:
        return "Insufficient evidence"
    if strong:
        return "Strong"
    if consistent:
        return "Consistent"
    return "Developing"


def developer_metrics(rows):
    grouped = {}
    for row in rows:
        author = row.get("author_login") or "Unknown"
        grouped.setdefault(author, []).append(row)
    metrics = []
    for author, items in sorted(grouped.items()):
        closed = [row for row in items if row.get("pr_state") in {"merged", "closed"}]
        merged = [row for row in items if row.get("pr_state") == "merged"]
        lead_times = [
            number(row.get("lead_time_hours"), None)
            for row in merged
            if row.get("lead_time_hours") is not None
        ]
        first_attempts = sum(int(number(row.get("ci_first_attempts"))) for row in items)
        first_passes = sum(int(number(row.get("ci_first_passes"))) for row in items)
        completion_rate = 100 * len(merged) / len(closed) if closed else None
        median_lead = statistics.median(lead_times) if lead_times else None
        first_pass_rate = (
            100 * first_passes / first_attempts if first_attempts else None
        )
        requested = sum(int(number(row.get("changes_requested"))) for row in items)
        requests_per_merged = requested / len(merged) if merged else None
        assessed = [
            row
            for row in items
            if row.get("assessment_status") == "assessed"
            and row.get("estimated_ai_assistance_pct") is not None
        ]
        ai_estimates = [number(row.get("estimated_ai_assistance_pct")) for row in assessed]
        delivery_level = competency_level(
            len(closed),
            completion_rate is not None
            and completion_rate >= 90
            and median_lead is not None
            and median_lead <= 72,
            completion_rate is not None
            and completion_rate >= 70
            and median_lead is not None
            and median_lead <= 120,
        )
        quality_level = competency_level(
            min(len(merged), first_attempts),
            first_pass_rate is not None
            and first_pass_rate >= 90
            and requests_per_merged is not None
            and requests_per_merged <= 0.5,
            first_pass_rate is not None
            and first_pass_rate >= 75
            and requests_per_merged is not None
            and requests_per_merged <= 1,
        )
        metrics.append(
            {
                "developer": author,
                "tracked_prs": len(items),
                "open_prs": sum(row.get("pr_state") == "open" for row in items),
                "closed_prs": len(closed),
                "merged_prs": len(merged),
                "closed_pr_completion_rate": (
                    round(completion_rate, 2) if completion_rate is not None else None
                ),
                "median_merge_lead_time_hours": (
                    round(median_lead, 2) if median_lead is not None else None
                ),
                "ci_first_attempts": first_attempts,
                "ci_first_passes": first_passes,
                "ci_first_pass_rate": (
                    round(first_pass_rate, 2) if first_pass_rate is not None else None
                ),
                "ci_failures": sum(
                    int(number(row.get("workflow_failures"))) for row in items
                ),
                "changes_requested": requested,
                "review_rework_prs": sum(
                    number(row.get("review_iterations")) > 0 for row in items
                ),
                "ai_assessed_prs": len(assessed),
                "median_estimated_ai_assistance_pct": (
                    round(statistics.median(ai_estimates), 2) if ai_estimates else None
                ),
                "delivery_level": delivery_level,
                "quality_level": quality_level,
                "framework_version": "github-poc-v1",
            }
        )
    return metrics


def workspace_id():
    me = request("GET", "/me")
    for workspace in me.get("workspaces") or []:
        if workspace.get("name") == WORKSPACE_NAME:
            return workspace["id"]
    created = request("POST", "/workspaces", {"name": WORKSPACE_NAME})
    return created["id"]


def dataset_id(workspace, name):
    listed = request("GET", f"/workspaces/{workspace}/resources/dataset?limit=100")
    for item in listed.get("items") or []:
        if item.get("name") == name:
            return item["id"]
    return None


def ingest(workspace, name, rows):
    existing = dataset_id(workspace, name)
    body = {"name": name, "rows": rows}
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


def save_board(workspace, datasets):
    def widget(title, why, kind, source, sql, format="number"):
        return {
            "title": title,
            "why": why,
            "kind": kind,
            "format": format,
            "source": source,
            "sql": sql,
            "inputs": [datasets[source]],
        }

    board = request(
        "PUT",
        f"/workspaces/{workspace}/home/board",
        {
            "name": "Engineering performance POC",
            "widgets": [
                widget(
                    "Delivery · PRs tracked",
                    "One canonical row per pull request. Synchronize and close events do not add duplicate PRs.",
                    "kpi",
                    PR_DATASET,
                    f"SELECT COUNT(*) AS value FROM {PR_DATASET}",
                ),
                widget(
                    "Delivery · PRs merged",
                    "Merged pull requests across the loaded evidence period.",
                    "kpi",
                    PR_DATASET,
                    f"SELECT SUM(CASE WHEN pr_state = 'merged' THEN 1 ELSE 0 END) AS value FROM {PR_DATASET}",
                ),
                widget(
                    "Delivery · Closed PR completion",
                    "Merged PRs divided by closed PRs. Open work is excluded.",
                    "kpi",
                    DEVELOPER_DATASET,
                    f"SELECT 100.0 * SUM(merged_prs) / NULLIF(SUM(closed_prs), 0) AS value FROM {DEVELOPER_DATASET}",
                    "percent",
                ),
                widget(
                    "Delivery · Median merge lead time",
                    "Hours from PR creation to merge. This is flow time, not coding time.",
                    "kpi",
                    PR_DATASET,
                    f"SELECT MEDIAN(lead_time_hours) AS value FROM {PR_DATASET} WHERE pr_state = 'merged' AND lead_time_hours IS NOT NULL",
                ),
                widget(
                    "Delivery · PR state",
                    "Current lifecycle state for each canonical pull request.",
                    "breakdown",
                    PR_DATASET,
                    f"SELECT pr_state AS label, COUNT(*) AS value FROM {PR_DATASET} GROUP BY pr_state ORDER BY value DESC",
                ),
                widget(
                    "Delivery · Competency signal",
                    "Provisional POC rubric. Fewer than three closed PRs remains insufficient evidence.",
                    "breakdown",
                    DEVELOPER_DATASET,
                    f"SELECT delivery_level AS label, COUNT(*) AS value FROM {DEVELOPER_DATASET} GROUP BY delivery_level ORDER BY value DESC",
                ),
                widget(
                    "Quality · First-pass CI",
                    "Successful first attempts divided by completed first attempts, excluding this judgment workflow.",
                    "kpi",
                    DEVELOPER_DATASET,
                    f"SELECT 100.0 * SUM(ci_first_passes) / NULLIF(SUM(ci_first_attempts), 0) AS value FROM {DEVELOPER_DATASET}",
                    "percent",
                ),
                widget(
                    "Quality · Failed CI attempts",
                    "Failure, timeout, action-required, and startup-failure conclusions.",
                    "kpi",
                    DEVELOPER_DATASET,
                    f"SELECT COALESCE(SUM(ci_failures), 0) AS value FROM {DEVELOPER_DATASET}",
                ),
                widget(
                    "Quality · Changes requested",
                    "Submitted CHANGES_REQUESTED reviews across tracked PRs.",
                    "kpi",
                    DEVELOPER_DATASET,
                    f"SELECT COALESCE(SUM(changes_requested), 0) AS value FROM {DEVELOPER_DATASET}",
                ),
                widget(
                    "Quality · PRs with review rework",
                    "PRs with a commit after a changes-requested review.",
                    "kpi",
                    DEVELOPER_DATASET,
                    f"SELECT COALESCE(SUM(review_rework_prs), 0) AS value FROM {DEVELOPER_DATASET}",
                ),
                widget(
                    "Quality · First-pass CI by developer",
                    "This is a reliability signal, not a developer ranking.",
                    "breakdown",
                    DEVELOPER_DATASET,
                    f"SELECT developer AS label, ci_first_pass_rate AS value FROM {DEVELOPER_DATASET} WHERE ci_first_pass_rate IS NOT NULL ORDER BY value DESC",
                    "percent",
                ),
                widget(
                    "Quality · Competency signal",
                    "Provisional POC rubric using first-pass CI and requested-change evidence.",
                    "breakdown",
                    DEVELOPER_DATASET,
                    f"SELECT quality_level AS label, COUNT(*) AS value FROM {DEVELOPER_DATASET} GROUP BY quality_level ORDER BY value DESC",
                ),
                widget(
                    "AI assistance · PRs assessed",
                    "Pull requests with a Gemini estimate based on their changed code diff.",
                    "kpi",
                    PR_DATASET,
                    f"SELECT COUNT(*) AS value FROM {PR_DATASET} WHERE assessment_status = 'assessed'",
                ),
                widget(
                    "AI assistance · Median estimate",
                    "Median approximate AI-assistance estimate across assessed pull request diffs.",
                    "kpi",
                    PR_DATASET,
                    f"SELECT MEDIAN(estimated_ai_assistance_pct) AS value FROM {PR_DATASET} WHERE assessment_status = 'assessed'",
                    "percent",
                ),
                widget(
                    "AI assistance · Estimate by PR",
                    "Approximate Gemini estimate based only on each pull request's changed code diff.",
                    "breakdown",
                    PR_DATASET,
                    f"SELECT '#' || CAST(pull_request AS VARCHAR) || ' · ' || title AS label, estimated_ai_assistance_pct AS value FROM {PR_DATASET} WHERE assessment_status = 'assessed' ORDER BY pull_request DESC",
                    "percent",
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
    developers = developer_metrics(rows)
    workspace = workspace_id()
    datasets = {
        PR_DATASET: ingest(workspace, PR_DATASET, rows),
        DEVELOPER_DATASET: ingest(workspace, DEVELOPER_DATASET, developers),
    }
    ensure_published(workspace)
    board = save_board(workspace, datasets)
    print(
        json.dumps(
            {
                "workspace": workspace,
                "datasets": datasets,
                "rows": len(rows),
                "developers": len(developers),
                "widgets": [item.get("title") for item in board.get("widgets") or []],
                "url": ORIGIN + "/",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
