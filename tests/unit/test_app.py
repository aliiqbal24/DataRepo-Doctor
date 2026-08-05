from fastapi.testclient import TestClient

from datarepo_doctor.app import create_app
from datarepo_doctor.checks import PROBES
from datarepo_doctor.config import Settings
from datarepo_doctor.models import FailureMode
from datarepo_doctor.runner import ProcessProbeExecutor
from datarepo_doctor.storage import DoctorRepository


def _client(tmp_path):
    repository = DoctorRepository(f"sqlite:///{tmp_path / 'app.db'}")
    app = create_app(
        settings=Settings(database_url=str(repository.engine.url), schedules_enabled=False),
        repository=repository,
    )
    return TestClient(app), repository


def test_static_dashboard_and_complete_safe_check_contract(tmp_path):
    client, _repository = _client(tmp_path)
    with client:
        page = client.get("/")
        script = client.get("/static/app.js")
        checks = client.get("/api/checks")

    assert page.status_code == 200
    assert "DataRepo Doctor" in page.text
    assert "React" not in page.text
    assert script.status_code == 200
    assert checks.status_code == 200
    payload = checks.json()[0]
    assert "database.table" in payload["query_code"]
    assert payload["displays_result_rows"] is True
    assert "validation_contract" not in payload
    assert "filters" not in payload
    assert "arguments" not in payload


def test_trimmed_api_and_persisted_schedule_controls(tmp_path):
    client, _repository = _client(tmp_path)
    check_id = PROBES[0].check_id
    with client:
        assert client.get(f"/api/checks/{check_id}").status_code == 404
        assert client.get("/api/summary").status_code == 404
        response = client.patch(
            f"/api/checks/{check_id}/schedule",
            json={"enabled": False, "interval_minutes": 120},
        )
        refreshed = client.get("/api/checks").json()[0]

    assert response.status_code == 200
    assert refreshed["schedule"]["enabled"] is False
    assert refreshed["schedule"]["interval_minutes"] == 120


def test_unhealthy_api_outcome_has_safe_detail_and_no_latency(tmp_path):
    client, repository = _client(tmp_path)
    outcome = ProcessProbeExecutor._failure(
        PROBES[0],
        FailureMode.TIMEOUT,
        "The probe reached its safety timeout.",
        500,
    )
    with client:
        repository.save_outcome(outcome)
        result = client.get("/api/checks").json()[0]["latest_outcome"]

    assert result["health"] == "unhealthy"
    assert result["user_query_latency_ms"] is None
    assert result["failure_detail"] == "ProcessTimeout"
    assert result["result_rows"] == []
