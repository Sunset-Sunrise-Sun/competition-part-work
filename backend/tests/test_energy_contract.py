import json
from pathlib import Path
import pytest
from app.energy import session_energy

CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/energy_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", CASES, ids=[x["name"] for x in CASES])
def test_shared_energy_goldens(entry):
    actual = session_energy(entry["exercise"], entry["weightKg"], entry["activeSeconds"],
                            entry["observableSeconds"], [], work_seconds=entry["workSeconds"], rest_seconds=entry["restSeconds"])
    for key, expected in entry["expected"].items():
        assert actual[key] == expected, key


def test_count_does_not_imply_work():
    result = session_energy("squat",65,60,0,[],reps=100)
    assert result["work_seconds"] == 0
    assert result["unknown_seconds"] == 60
    assert not result["available"]


PLAN_CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/plan_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", PLAN_CASES, ids=[x["name"] for x in PLAN_CASES])
def test_shared_plan_goldens(entry):
    from app.agents import analyze
    from app.schemas import SessionSummary
    summary = dict(session_id="plan-contract",exercise="squat",source="simulation",reps=12,
                   active_seconds=60,observable_seconds=55,form_events=0,fatigue=4,discomfort=False,
                   target_reps=12,profile={"weight_kg":65})
    summary.update(entry["input"])
    actual = analyze(SessionSummary(**summary))
    for key,expected in entry["expected"].items():
        assert actual["proposal"][key] == expected, key


DAILY_CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/daily_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", DAILY_CASES, ids=[x["name"] for x in DAILY_CASES])
def test_shared_daily_rounding(entry):
    from app.energy import daily_requirement
    from app.schemas import Profile
    data=entry['input']
    actual=daily_requirement(Profile(weight_kg=data['weightKg'],height_cm=data['heightCm'],age_years=data['ageYears'],
                                     sex=data['sex'],activity=data['activity'],goal=data['goal']))
    for key,expected in entry['expected'].items():
        assert actual[key] == expected, key
