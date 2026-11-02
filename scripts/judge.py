import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def text(name):
    raw = os.environ.get(name, "").strip()
    if raw == "" or raw.lower() == "null":
        return None
    return raw


def whole(name):
    raw = text(name)
    if raw is None:
        return None
    return int(raw)


def github_json(token, url):
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "helix-judgment",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
        return payload, response.headers.get("Link")


def github_pages(token, url):
    items = []
    while url:
        payload, link = github_json(token, url)
        if isinstance(payload, dict):
            raise SystemExit(f"GitHub list was not a list: {url}")
        items.extend(payload)
        url = None
        for part in (link or "").split(","):
            if 'rel="next"' in part:
                url = part[part.find("<") + 1 : part.find(">")]
    return items


def count_iterations(reviews, commits):
    events = []
    for review in reviews:
        submitted = review.get("submitted_at")
        if review.get("state") == "CHANGES_REQUESTED" and submitted:
            events.append((submitted, "request"))
    for commit in commits:
        commit_time = (commit.get("commit") or {}).get("committer") or {}
        when = commit_time.get("date")
        if when:
            events.append((when, "commit"))
    events.sort()
    changes_requested = 0
    iterations = 0
    waiting = False
    for _, kind in events:
        if kind == "request":
            changes_requested += 1
            waiting = True
        elif waiting:
            iterations += 1
            waiting = False
    return changes_requested, iterations


def github_metrics(repository, number):
    blank = {
        "review_comments": None,
        "changes_requested": None,
        "review_iterations": None,
        "workflow_runs": None,
        "workflow_failures": None,
    }
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token or not repository or not number:
        return blank
    base = f"https://api.github.com/repos/{repository}"
    pull, _ = github_json(token, f"{base}/pulls/{number}")
    reviews = github_pages(token, f"{base}/pulls/{number}/reviews?per_page=100")
    commits = github_pages(token, f"{base}/pulls/{number}/commits?per_page=100")
    changes_requested, iterations = count_iterations(reviews, commits)
    seen = {}
    for sha in [commit.get("sha") for commit in commits if commit.get("sha")]:
        runs, _ = github_json(
            token, f"{base}/actions/runs?head_sha={sha}&per_page=100"
        )
        for run in runs.get("workflow_runs") or []:
            seen[run.get("id")] = run.get("conclusion")
    return {
        "review_comments": pull.get("review_comments"),
        "changes_requested": changes_requested,
        "review_iterations": iterations,
        "workflow_runs": len(seen),
        "workflow_failures": sum(1 for conclusion in seen.values() if conclusion == "failure"),
    }


def judge():
    authors = []
    if os.path.exists("commit_authors.txt"):
        for line in open("commit_authors.txt", encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and line not in authors:
                authors.append(line)

    diff = ""
    if os.path.exists("diff.txt"):
        diff = open("diff.txt", encoding="utf-8", errors="replace").read()
    sent = diff[:12000]
    skip_model = os.environ.get("SKIP_MODEL", "").strip() == "1"
    empty = not diff.strip()

    ai_generated = None
    confidence = None
    model = None
    if skip_model:
        reason = "Already judged on the pull request. The merge was not sent to the model again."
    elif empty:
        reason = "No application code changed in this pull request, so it was not sent to the model."
    else:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit(
                "GEMINI_API_KEY is empty. In the GitHub repo open Settings, "
                "Secrets and variables, Actions, and add a secret named GEMINI_API_KEY."
            )
        model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        prompt = (
            "You are judging a pull request diff. Decide whether an AI coding agent "
            "wrote the changed code. You only have the diff. Reply with JSON only, "
            "no markdown: "
            '{"ai_generated": true or false, "confidence": 0 to 1, "reason": "one sentence"}'
        )
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt + "\n\nDIFF:\n" + sent}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        ).encode()
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        print(f"Asking {model}. Diff length: {len(sent)} characters.", flush=True)
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2000]
            raise SystemExit(f"Gemini returned HTTP {error.code} for model {model}:\n{detail}")
        except TimeoutError:
            raise SystemExit(
                f"{model} did not answer within 3 minutes. "
                "Re-run the job, or set GEMINI_MODEL to a faster model such as gemini-3.5-flash-lite."
            )
        answer = json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
        if not isinstance(answer.get("ai_generated"), bool):
            raise SystemExit("The model did not return ai_generated as true or false.")
        try:
            confidence = float(answer.get("confidence"))
        except (TypeError, ValueError):
            raise SystemExit("The model did not return a numeric confidence.")
        confidence = max(0.0, min(1.0, confidence))
        ai_generated = answer["ai_generated"]
        reason = str(answer.get("reason") or "").strip() or "The model gave no reason."

    if ai_generated is True:
        mark = "Marked AI"
    elif ai_generated is False:
        mark = "Not marked AI"
    else:
        mark = "Not judged"

    row = {
        "repository": text("REPOSITORY"),
        "pull_request": whole("PULL_REQUEST"),
        "title": text("PR_TITLE"),
        "url": text("PR_URL"),
        "author_login": text("AUTHOR_LOGIN"),
        "commit_authors": "; ".join(authors) or None,
        "head_branch": text("HEAD_BRANCH"),
        "base_branch": text("BASE_BRANCH"),
        "head_sha": text("HEAD_SHA"),
        "base_sha": text("BASE_SHA"),
        "commits": whole("COMMITS"),
        "additions": whole("ADDITIONS"),
        "deletions": whole("DELETIONS"),
        "changed_files": whole("CHANGED_FILES"),
        "created_at": text("CREATED_AT"),
        "updated_at": text("UPDATED_AT"),
        "merged": text("MERGED") == "true",
        "merged_at": text("MERGED_AT"),
        "merge_commit_sha": text("MERGE_COMMIT_SHA"),
        "event": text("EVENT"),
        "judged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "ai_generated": ai_generated,
        "confidence": confidence,
        "mark": mark,
        "reason": reason,
        "diff_characters": 0 if skip_model else len(sent),
        "diff_truncated": False if skip_model else len(diff) > 12000,
    }
    try:
        row.update(github_metrics(row.get("repository"), row.get("pull_request")))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise SystemExit(f"GitHub returned HTTP {error.code}:\n{detail}")
    print(json.dumps(row, indent=2))
    open("judgment.json", "w", encoding="utf-8").write(json.dumps(row, indent=2) + "\n")


def metrics_for_saved(paths):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from load_helix import collapse

    rows = [json.load(open(path, encoding="utf-8")) for path in paths]
    combined = collapse(rows)
    if len(combined) != 1:
        raise SystemExit("The saved files must be one pull request.")
    row = combined[0]
    try:
        row.update(github_metrics(row.get("repository"), row.get("pull_request")))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise SystemExit(f"GitHub returned HTTP {error.code}:\n{detail}")
    destination = os.path.join(os.path.dirname(os.path.dirname(paths[0])), "pr-1.json")
    open(destination, "w", encoding="utf-8").write(json.dumps(row, indent=2) + "\n")
    print(json.dumps(row, indent=2))
    print(f"Wrote {destination}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--from-saved":
        if len(sys.argv) < 3:
            raise SystemExit(
                "Usage: python3 scripts/judge.py --from-saved judgments/opened/judgment.json judgments/merged/judgment.json"
            )
        metrics_for_saved(sys.argv[2:])
    else:
        judge()
