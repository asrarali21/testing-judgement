import json
import os
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
print(json.dumps(row, indent=2))
open("judgment.json", "w", encoding="utf-8").write(json.dumps(row, indent=2) + "\n")
