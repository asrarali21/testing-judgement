import json
import os
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

tool_fields = {
    "judge_tool": None,
    "synthetic_code_score": None,
    "match_count": None,
}
ai_generated = None
confidence = None
model = None
if skip_model:
    reason = "Already judged on the pull request. The merge was not sent to the scanner again."
elif empty:
    reason = "No application code changed in this pull request, so it was not scanned."
elif not os.path.exists("synthscan-report.json"):
    raise SystemExit("SynthScan did not write synthscan-report.json.")
else:
    report = json.load(open("synthscan-report.json", encoding="utf-8"))
    score = float(report.get("synthetic_code_score") or 0)
    matches = int(report.get("match_count") or 0)
    # SynthScan's own bands: 0–5 likely human, 5–15 low signal, 15 and above moderate.
    ai_generated = score >= 15
    confidence = max(0.0, min(1.0, score / 30))
    reason = (
        f"SynthScan score {score} per 1,000 lines, {matches} pattern matches. "
        + (
            "That is in the moderate-or-higher band."
            if ai_generated
            else "That is below the moderate band."
        )
    )
    tool_fields = {
        "judge_tool": "synthscan",
        "synthetic_code_score": score,
        "match_count": matches,
    }
    print(
        f"SynthScan score {score}, matches {matches}, diff {len(sent)} characters.",
        flush=True,
    )

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
    "judge_tool": tool_fields["judge_tool"],
    "synthetic_code_score": tool_fields["synthetic_code_score"],
    "match_count": tool_fields["match_count"],
    "diff_characters": 0 if skip_model else len(sent),
    "diff_truncated": False if skip_model else len(diff) > 12000,
}
print(json.dumps(row, indent=2))
open("judgment.json", "w", encoding="utf-8").write(json.dumps(row, indent=2) + "\n")
