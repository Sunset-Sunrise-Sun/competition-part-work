"""Synthetic end-to-end API smoke test against an already running local backend."""
import json
from urllib.request import Request, urlopen
from uuid import uuid4


def call(path, payload=None):
    req = Request("http://127.0.0.1:8000/api" + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


assert call("/health")["status"] == "ok"
session = uuid4().hex
report = call("/sessions/analyze", {"session_id": session, "exercise": "squat", "source": "simulation",
    "reps": 8, "active_seconds": 60, "observable_seconds": 55, "form_events": 1,
    "fatigue": 8, "target_reps": 12, "persist": False})
assert report["proposal"]["target_reps"] < 12
assert not report["saved"]
assert call(f"/sessions/{session}/accept", {"input_version": 1})["proposal"]["status"] == "accepted"
assert call("/nutrition/estimate", [{"food_id": "rice", "grams": 150}])["total_kcal"] == 195
print("PASS: health -> synthetic summary -> proposal -> acceptance -> illustrative nutrition; no persistence")
