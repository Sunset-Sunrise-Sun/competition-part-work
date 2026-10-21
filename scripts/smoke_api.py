"""Synthetic end-to-end API smoke test against an already running local backend."""
import json
import argparse
from urllib.request import Request, urlopen
from uuid import uuid4

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8000')
args = parser.parse_args()


def call(path, payload=None):
    req = Request(args.base_url.rstrip('/') + "/api" + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


assert call("/health")["status"] == "ok"
session = uuid4().hex
report = call("/sessions/analyze", {"session_id": session, "exercise": "squat", "source": "simulation",
    "reps": 8, "active_seconds": 60, "observable_seconds": 55, "form_events": 1,
    "fatigue": 8, "target_reps": 12, "persist": False,
    "work_seconds":30,"rest_seconds":20,
    "rep_details": [{"number": 1, "start_seconds": 1, "bottom_seconds": 2, "end_seconds": 3,
                     "descent_seconds": 1, "ascent_seconds": 1, "min_angle_degrees": 120,
                     "rom": "below_rule"}]})
assert report["proposal"]["target_reps"] < 12
assert not report["saved"]
assert report["rep_details"][0]["rom"] == "below_rule"
assert report["trace"][0]["evidence"]["experimental_rom"]["below_rule"] == 1
assert report["energy"]["work_seconds"] == 30
assert report["energy"]["unknown_seconds"] == 10
assert report["energy"]["low_kcal"] == 2.4
assert call(f"/sessions/{session}/accept", {"input_version": 1})["proposal"]["status"] == "accepted"
assert call(f"/sessions/{session}/accept", {"input_version": 1})["proposal"]["status"] == "accepted"
second=uuid4().hex
second_report=call('/sessions/analyze',{'session_id':second,'exercise':'jumping_jack','source':'simulation',
    'reps':12,'active_seconds':60,'observable_seconds':0,'work_seconds':0,'rest_seconds':0,
    'form_events':0,'fatigue':4,'persist':False})
assert second_report['energy']['available'] is False
rejected=call(f'/sessions/{second}/reject',{'input_version':1,'proposal_id':second_report['proposal']['proposal_id']})
assert rejected['proposal']['status']=='rejected'
assert rejected['proposal']['decided_at']
assert call("/nutrition/estimate", [{"food_id": "rice", "grams": 150}])["total_kcal"] == 195
print("PASS: health -> observed/unknown energy -> proposal acceptance/rejection -> illustrative nutrition; no persistence")
