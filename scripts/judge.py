import json, os, urllib.request

diff = open("diff.txt", encoding="utf-8", errors="replace").read()[:12000]
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
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": os.environ["GEMINI_API_KEY"],
    },
)
with urllib.request.urlopen(req, timeout=60) as response:
    payload = json.load(response)
text = payload["candidates"][0]["content"]["parts"][0]["text"]
print(text)
open("judgment.json", "w", encoding="utf-8").write(text + "\n")