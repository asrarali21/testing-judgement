import json, os, urllib.error, urllib.request

key = os.environ.get("GEMINI_API_KEY", "").strip()
if not key:
    raise SystemExit(
        "GEMINI_API_KEY is empty. In the GitHub repo open Settings, "
        "Secrets and variables, Actions, and add a secret named GEMINI_API_KEY."
    )

diff = open("diff.txt", encoding="utf-8", errors="replace").read()[:12000]
if not diff.strip():
    diff = "(empty diff)"
prompt = (
    "You are judging a git diff. Decide whether an AI coding agent wrote the changed code. "
    "You only have the diff. Reply with JSON only, no markdown: "
    '{"ai_generated": true or false, "confidence": 0 to 1, "reason": "one sentence"}'
)
body = json.dumps({
    "contents": [{"parts": [{"text": prompt + "\n\nDIFF:\n" + diff}]}],
    "generationConfig": {"responseMimeType": "application/json"},
}).encode()
model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
req = urllib.request.Request(
    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    data=body,
    headers={"Content-Type": "application/json", "x-goog-api-key": key},
)
print(f"Asking {model}. Diff length: {len(diff)} characters.", flush=True)
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
text = payload["candidates"][0]["content"]["parts"][0]["text"]
print(text)
open("judgment.json", "w", encoding="utf-8").write(text + "\n")