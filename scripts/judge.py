import json
import os
import time
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


def instant(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def elapsed_hours(start, end):
    a, b = instant(start), instant(end)
    if not a or not b:
        return None
    return round(max(0, (b - a).total_seconds() / 3600), 2)


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
        "approvals": None,
        "changes_requested": None,
        "review_iterations": None,
        "first_review_at": None,
        "first_review_response_hours": None,
        "commits_after_first_review": None,
        "workflow_runs": None,
        "workflow_failures": None,
        "workflow_cancelled": None,
        "ci_first_attempts": None,
        "ci_first_passes": None,
        "ci_first_pass_rate": None,
        "ci_recoveries": None,
    }
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token or not repository or not number:
        return blank
    base = f"https://api.github.com/repos/{repository}"
    pull, _ = github_json(token, f"{base}/pulls/{number}")
    reviews = github_pages(token, f"{base}/pulls/{number}/reviews?per_page=100")
    commits = github_pages(token, f"{base}/pulls/{number}/commits?per_page=100")
    changes_requested, iterations = count_iterations(reviews, commits)
    submitted = sorted(
        review.get("submitted_at")
        for review in reviews
        if review.get("submitted_at")
        and review.get("state") not in {"PENDING", "DISMISSED"}
    )
    first_review = submitted[0] if submitted else None
    commits_after_review = 0
    if first_review:
        first_review_time = instant(first_review)
        commits_after_review = sum(
            1
            for commit in commits
            if instant(
                ((commit.get("commit") or {}).get("committer") or {}).get("date")
            )
            and instant(
                ((commit.get("commit") or {}).get("committer") or {}).get("date")
            )
            > first_review_time
        )
    seen = {}
    excluded_workflow = os.environ.get(
        "JUDGMENT_WORKFLOW_NAME", "Judge pull request"
    ).strip()
    for sha in [commit.get("sha") for commit in commits if commit.get("sha")]:
        runs, _ = github_json(
            token, f"{base}/actions/runs?head_sha={sha}&per_page=100"
        )
        for run in runs.get("workflow_runs") or []:
            if run.get("name") == excluded_workflow:
                continue
            seen[run.get("id")] = run
    grouped = {}
    for run in seen.values():
        workflow = run.get("workflow_id") or run.get("name")
        key = (run.get("head_sha"), workflow)
        grouped.setdefault(key, []).append(run)
    first_attempts = 0
    first_passes = 0
    recoveries = 0
    for attempts in grouped.values():
        completed = [run for run in attempts if run.get("conclusion")]
        if not completed:
            continue
        completed.sort(
            key=lambda run: (
                int(run.get("run_attempt") or 1),
                run.get("created_at") or "",
            )
        )
        first_attempts += 1
        first_passes += completed[0].get("conclusion") == "success"
        recoveries += (
            completed[0].get("conclusion") != "success"
            and any(run.get("conclusion") == "success" for run in completed[1:])
        )
    conclusions = [
        run.get("conclusion") for run in seen.values() if run.get("conclusion")
    ]
    failed = {"failure", "timed_out", "action_required", "startup_failure"}
    return {
        "review_comments": pull.get("review_comments"),
        "approvals": sum(1 for review in reviews if review.get("state") == "APPROVED"),
        "changes_requested": changes_requested,
        "review_iterations": iterations,
        "first_review_at": first_review,
        "first_review_response_hours": elapsed_hours(
            pull.get("created_at"), first_review
        ),
        "commits_after_first_review": commits_after_review,
        "workflow_runs": len(conclusions),
        "workflow_failures": sum(1 for conclusion in conclusions if conclusion in failed),
        "workflow_cancelled": sum(
            1 for conclusion in conclusions if conclusion == "cancelled"
        ),
        "ci_first_attempts": first_attempts,
        "ci_first_passes": first_passes,
        "ci_first_pass_rate": (
            round(100 * first_passes / first_attempts, 2)
            if first_attempts
            else None
        ),
        "ci_recoveries": recoveries,
    }


def parse_assessment(answer):
    status = str(answer.get("assessment_status") or "")
    if status not in {"assessed", "insufficient_evidence"}:
        raise ValueError("assessment_status must be assessed or insufficient_evidence")
    percentage = answer.get("estimated_ai_assistance_pct")
    if status == "assessed":
        if not isinstance(percentage, int) or isinstance(percentage, bool):
            raise ValueError("assessed requires an integer percentage")
        if not 0 <= percentage <= 100:
            raise ValueError("estimated_ai_assistance_pct must be from 0 to 100")
    elif percentage is not None:
        raise ValueError("insufficient_evidence requires a null percentage")
    raw_evidence = answer.get("evidence")
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 3:
        raise ValueError("evidence must be a list with at most three items")
    return status, percentage, [
        str(item).strip() for item in raw_evidence if str(item).strip()
    ]


def gemini_assessment(key, model, prompt, diff):
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt + "\n\nDIFF:\n" + diff}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
    ).encode()
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    return parse_assessment(
        json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
    )


def groq_assessment(key, model, prompt, diff):
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only the requested JSON object."},
                {"role": "user", "content": prompt + "\n\nDIFF:\n" + diff},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "helix-pr-judgment/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    return parse_assessment(json.loads(payload["choices"][0]["message"]["content"]))


def retry_assessment(provider, request, attempts):
    errors = []
    for attempt in range(attempts):
        try:
            return request(), None
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            try:
                payload = json.loads(detail)
                if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                    detail = str(payload["error"].get("message", detail))
            except json.JSONDecodeError:
                pass
            message = f"{provider} returned HTTP {error.code}: {detail}".strip()
            retryable = error.code in {429, 500, 502, 503, 504}
        except (TimeoutError, urllib.error.URLError) as error:
            message = f"{provider} request failed: {error}"
            retryable = True
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            message = f"{provider} returned an invalid assessment: {error}"
            retryable = False
        errors.append(message)
        if not retryable or attempt == attempts - 1:
            break
        time.sleep(10 * (attempt + 1))
    return None, " ".join(errors)


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

assessment_status = "unavailable"
estimated_ai_assistance_pct = None
evidence = []
assessment_error = None
model = None
judge_tool = None
if skip_model:
    reason = "Lifecycle update only. The pull request was not assessed again."
elif empty:
    assessment_status = "insufficient_evidence"
    reason = "No application code changed in this pull request."
else:
    prompt = (
        "Assess only the supplied pull request diff. Estimate the approximate "
        "percentage of changed code that appears AI-assisted. This is an uncertain "
        "heuristic, not an authorship determination and not an assessment of the "
        "developer. Return JSON only with exactly these keys: "
        '{"assessment_status":"assessed" or "insufficient_evidence", '
        '"estimated_ai_assistance_pct": integer from 0 to 100 or null, '
        '"evidence": [up to three short, concrete observations about the diff]}. '
        "Use insufficient_evidence with a null percentage when the diff cannot "
        "support an estimate."
    )
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    groq_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    errors = []
    if gemini_key and gemini_model:
        print(f"Asking {gemini_model}. Diff length: {len(sent)} characters.", flush=True)
        result, error = retry_assessment(
            "Gemini",
            lambda: gemini_assessment(gemini_key, gemini_model, prompt, sent),
            attempts=3,
        )
        if result:
            assessment_status, estimated_ai_assistance_pct, evidence = result
            model = gemini_model
            judge_tool = "gemini"
        else:
            errors.append(error)
    else:
        errors.append("GEMINI_API_KEY or GEMINI_MODEL is not configured.")
    if judge_tool is None and groq_key and groq_model:
        print(f"Falling back to {groq_model}.", flush=True)
        result, error = retry_assessment(
            "Groq",
            lambda: groq_assessment(groq_key, groq_model, prompt, sent),
            attempts=1,
        )
        if result:
            assessment_status, estimated_ai_assistance_pct, evidence = result
            model = groq_model
            judge_tool = "groq"
        else:
            errors.append(error)
    elif judge_tool is None:
        errors.append("GROQ_API_KEY or GROQ_MODEL is not configured.")
    if judge_tool is None:
        assessment_error = " ".join(error for error in errors if error)
        reason = assessment_error
    else:
        reason = evidence[0] if evidence else "No diff-specific evidence returned."

mark = "AI assistance assessed" if assessment_status == "assessed" else "Not assessed"

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
    "pr_state": (
        "merged"
        if text("MERGED") == "true"
        else "closed"
        if text("EVENT") == "closed"
        else "open"
    ),
    "lead_time_hours": elapsed_hours(text("CREATED_AT"), text("MERGED_AT")),
    "judged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "model": model,
    "assessment_status": assessment_status,
    "estimated_ai_assistance_pct": estimated_ai_assistance_pct,
    "evidence": evidence,
    "assessment_error": assessment_error,
    "mark": mark,
    "reason": reason,
    "judge_tool": judge_tool if not skip_model and not empty else None,
    "assessment_schema_version": "ai-assistance-v1",
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
