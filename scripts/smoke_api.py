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
    "fatigue": 8, "target_reps": 12, "persist": False,
    "rep_details": [{"number": 1, "start_seconds": 1, "bottom_seconds": 2, "end_seconds": 3,
                     "descent_seconds": 1, "ascent_seconds": 1, "min_angle_degrees": 120,
                     "rom": "below_rule"}]})
assert report["proposal"]["target_reps"] < 12
assert not report["saved"]
assert report["rep_details"][0]["rom"] == "below_rule"
assert report["trace"][0]["evidence"]["experimental_rom"]["below_rule"] == 1
assert call(f"/sessions/{session}/accept", {"input_version": 1})["proposal"]["status"] == "accepted"
assert call("/nutrition/estimate", [{"food_id": "rice", "grams": 150}])["total_kcal"] == 195
print("PASS: health -> synthetic summary -> proposal -> acceptance -> illustrative nutrition; no persistence")
