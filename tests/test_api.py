import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.service import APIService
from plant.generate import generate_dataset


@pytest.fixture(scope="module")
def generated_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("api-data")
    generate_dataset(
        "config/facility.yaml",
        "config/scenarios.yaml",
        "S1",
        117,
        output,
        days=1,
    )
    return output


@pytest.fixture
def client(generated_run, tmp_path):
    service = APIService(generated_run, tmp_path / "reports")
    return TestClient(create_app(service))


def test_scenarios_kpis_forecast_anomalies_and_cv_events(client):
    scenarios = client.get("/scenarios")
    assert scenarios.status_code == 200
    assert {item["id"] for item in scenarios.json()} == {"S1", "S2", "S3", "S4"}

    tariff = client.get("/tariff", headers={"Origin": "http://localhost:5173"})
    assert tariff.status_code == 200
    assert tariff.json()["synthetic"] is True
    assert tariff.json()["energy_inr_per_kwh"]["peak"] == 9.5
    assert tariff.headers["access-control-allow-origin"] == "http://localhost:5173"

    kpis = client.get("/kpis")
    assert kpis.status_code == 200
    assert kpis.json()["synthetic"] is True
    assert kpis.json()["energy_kwh"] > 0

    forecast = client.get("/forecast", params={"horizon_steps": 2})
    assert forecast.status_code == 200
    assert len(forecast.json()["points"]) == 2

    anomalies = client.get("/anomalies", params={"threshold_kw": 1})
    assert anomalies.status_code == 200
    assert anomalies.json()["synthetic"] is True

    events = client.get("/cv/events", params={"limit": 8})
    assert events.status_code == 200
    assert len(events.json()["events"]) == 8
    assert all("state_true" not in item for item in events.json()["events"])


def test_run_what_if_copilot_and_report(client):
    run = client.post("/run", json={"scenario": "S2", "seed": 7, "days": 1})
    assert run.status_code == 200
    assert run.json()["synthetic"] is True
    assert run.json()["manifest"]["scenario"] == "S2"

    what_if = client.post(
        "/what-if",
        json={
            "action": {
                "command_id": "test-command",
                "issued_at": "2025-01-01T08:00:00+05:30",
                "equipment_id": "CNC-01",
                "action": "STANDBY",
                "duration_min": 15,
                "rationale": "API contract test",
            },
            "horizon_min": 10,
            "seed": 4,
        },
    )
    assert what_if.status_code == 200
    assert what_if.json()["synthetic"] is True
    assert "energy_kwh" in what_if.json()["delta"]

    copilot = client.post("/copilot", json={"query": "Show the energy KPIs"})
    assert copilot.status_code == 200
    assert copilot.json()["tool"] == "get_kpis"

    report = client.get("/report")
    assert report.status_code == 200
    assert "SYNTHETIC DATA" in report.json()["markdown"]


def test_recommendation_decision_is_proposal_only(client):
    client.app.state.twin_service._plan_cache = {
        "mode": "human",
        "recommendations": [{"id": "rec-test"}],
    }
    decision = client.post("/recommendations/rec-test/reject")
    assert decision.status_code == 200
    assert decision.json()["status"] == "rejected"
    assert "no plant command was sent" in decision.json()["message"]
    approved = client.post("/recommendations/rec-test/apply")
    assert approved.status_code == 200
    scheduled = client.post(
        "/recommendations/rec-test/schedule",
        json={"scheduled_for": "2025-01-01T09:00:00+05:30"},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "scheduled"


def test_websocket_replay_supports_pause_seek_and_streams_observables(client):
    with client.websocket_connect("/ws/replay") as socket:
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        socket.send_json({"type": "speed", "value": 60})
        socket.send_json({"type": "pause", "value": True})
        socket.send_json({"type": "seek", "index": ready["frames"] - 1})
        socket.send_json({"type": "pause", "value": False})
        frame_message = socket.receive_json()
        while frame_message.get("type") != "frame":
            frame_message = socket.receive_json()
        assert frame_message["policy"] == "baseline"
        frame = frame_message["frame"]
        assert "meter_kw" in frame
        assert all("state_true" not in item for item in frame["twin_state"])
        assert frame["timestamp"]


def test_run_rejects_unknown_scenario(client):
    response = client.post("/run", json={"scenario": "unknown", "days": 1})
    assert response.status_code == 422


def test_what_if_rejects_unknown_equipment(client):
    response = client.post(
        "/what-if",
        json={
            "action": {
                "command_id": "bad-command",
                "issued_at": "2025-01-01T08:00:00+05:30",
                "equipment_id": "UNKNOWN",
                "action": "STANDBY",
                "duration_min": 15,
                "rationale": "invalid equipment",
            },
            "horizon_min": 10,
        },
    )
    assert response.status_code == 422
