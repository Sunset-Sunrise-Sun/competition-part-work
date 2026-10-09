from fastapi.testclient import TestClient
from app.main import app, reports
from app.schemas import SessionSummary
from app.agents import analyze

client = TestClient(app)


def payload(**updates):
    value = dict(session_id="test-session", exercise="squat", source="simulation", reps=8,
                 active_seconds=60, observable_seconds=55, form_events=0, fatigue=8)
    value.update(updates)
    return value


def test_fatigue_reduces_target_with_evidence():
    report = analyze(SessionSummary(**payload()))
    assert report["proposal"]["target_reps"] < 12
    assert report["proposal"]["rest_seconds"] == 90
    assert len(report["trace"]) == 4


def test_missing_evidence_does_not_adapt():
    report = analyze(SessionSummary(**payload(observable_seconds=10)))
    assert report["proposal"]["target_reps"] == 12


def test_discomfort_cannot_be_accepted():
    reports.clear()
    report = client.post("/api/sessions/analyze", json=payload(discomfort=True)).json()
    assert report["proposal"]["blocked"]
    assert client.post("/api/sessions/test-session/accept", json={"input_version": 1}).status_code == 409


def test_stale_write_and_accept_rejected():
    reports.clear()
    assert client.post("/api/sessions/analyze", json=payload()).status_code == 200
    assert client.post("/api/sessions/analyze", json=payload()).status_code == 409
    assert client.post("/api/sessions/test-session/accept", json={"input_version": 2}).status_code == 409


def test_invalid_observation_duration_rejected():
    assert client.post("/api/sessions/analyze", json=payload(observable_seconds=100)).status_code == 422


def test_no_persistence_without_consent(tmp_path, monkeypatch):
    from app import main
    from app.storage import Storage
    monkeypatch.setattr(main, "storage", Storage(tmp_path / "test.sqlite"))
    reports.clear()
    client.post("/api/sessions/analyze", json=payload())
    assert not (tmp_path / "test.sqlite").exists()


def test_energy_scales_with_weight_and_duration():
    a = analyze(SessionSummary(**payload(profile={"weight_kg": 50})))
    b = analyze(SessionSummary(**payload(profile={"weight_kg": 100})))
    assert abs(b["energy"]["low_kcal"] - 2 * a["energy"]["low_kcal"]) <= 0.1


def test_local_model_cannot_use_remote_endpoint(monkeypatch):
    import pytest
    from app.local_llm import local_endpoint
    monkeypatch.setenv("LOCAL_LLM_URL", "https://example.com")
    with pytest.raises(ValueError):
        local_endpoint()
