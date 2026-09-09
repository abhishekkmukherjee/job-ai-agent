"""API tests for profile, jobs, applications, dashboard and settings."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_profile_read_and_update_bumps_version(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Abhishek Mukherjee"
    assert "Python" in body["skills"]
    v = body["version"]
    r = client.patch("/api/profile", json={"notice_period": "30 days", "skills": ["Python", "Go"]})
    assert r.status_code == 200
    assert r.json()["version"] == v + 1
    assert r.json()["skills"] == ["Python", "Go"]


def test_profile_rejects_unknown_fields(client):
    r = client.patch("/api/profile", json={"favourite_colour": "blue"})
    assert r.status_code == 422


def test_jobs_list_and_filters(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 7
    assert len(data["items"]) == 7
    r = client.get("/api/jobs", params={"q": "nimbus"})
    assert r.json()["total"] == 1
    r = client.get("/api/jobs", params={"remote": "remote"})
    assert all(j["remote_type"] == "remote" for j in r.json()["items"])
    r = client.get("/api/jobs", params={"source": "sample", "page_size": 2, "page": 2})
    assert len(r.json()["items"]) == 2
    r = client.get("/api/jobs", params={"min_score": 50})
    assert r.json()["total"] == 0


def test_job_detail_and_dismiss(client):
    job_id = client.get("/api/jobs").json()["items"][0]["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["description"]
    r = client.patch(f"/api/jobs/{job_id}", json={"user_action": "DISMISSED"})
    assert r.json()["user_action"] == "DISMISSED"
    assert client.get("/api/jobs").json()["total"] == 6
    assert client.get("/api/jobs", params={"include_dismissed": True}).json()["total"] == 7
    assert client.get("/api/jobs/999999").status_code == 404


def test_application_lifecycle_and_duplicates(client):
    job_id = client.get("/api/jobs").json()["items"][0]["id"]
    r = client.post("/api/applications", json={"job_id": job_id})
    assert r.status_code == 201
    app = r.json()
    assert app["status"] == "SHORTLISTED"
    # duplicate application for the same job is rejected
    r = client.post("/api/applications", json={"job_id": job_id})
    assert r.status_code == 409
    # invalid transition
    r = client.patch(f"/api/applications/{app['id']}", json={"status": "APPLIED"})
    assert r.status_code == 409
    # valid path
    for status in ["APPROVED", "PREPARING", "READY_TO_APPLY", "APPLIED"]:
        r = client.patch(f"/api/applications/{app['id']}", json={"status": status})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status
    assert r.json()["applied_at"] is not None
    assert [h["status"] for h in r.json()["status_history"]][-1] == "APPLIED"
    # cannot delete a submitted application
    assert client.delete(f"/api/applications/{app['id']}").status_code == 409
    # job now reports its application
    j = client.get(f"/api/jobs/{job_id}").json()
    assert j["application_id"] == app["id"] and j["application_status"] == "APPLIED"
    r = client.get("/api/applications", params={"status": "APPLIED"})
    assert r.json()["total"] == 1


def test_application_update_fields(client):
    job_id = client.get("/api/jobs").json()["items"][1]["id"]
    app = client.post("/api/applications", json={"job_id": job_id, "status": "APPROVED"}).json()
    r = client.patch(
        f"/api/applications/{app['id']}",
        json={"notes": "call recruiter", "follow_up_date": "2026-09-20T09:00:00Z", "answers": [{"question": "Q", "answer": "A"}]},
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "call recruiter"
    assert r.json()["answers"][0]["question"] == "Q"
    assert client.delete(f"/api/applications/{app['id']}").status_code == 204
    assert client.get(f"/api/applications/{app['id']}").status_code == 404


def test_dashboard_counts(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    counts = r.json()["counts"]
    assert counts["jobs_discovered"] == 7
    assert counts["applications_submitted"] == 0


def test_settings_roundtrip(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "intern" in r.json()["filter_rules"]["reject_title_keywords"]
    r = client.patch("/api/settings", json={"career_pages": {"greenhouse": ["acme"], "lever": [], "ashby": []}})
    assert r.status_code == 200
    assert r.json()["career_pages"]["greenhouse"] == ["acme"]
    assert client.get("/api/settings").json()["career_pages"]["greenhouse"] == ["acme"]
    assert client.patch("/api/settings", json={"bogus": 1}).status_code == 422
    r = client.get("/api/settings/env")
    assert r.status_code == 200
    assert "gemini_configured" in r.json()


def test_interrupted_runs_are_failed_on_startup(db):
    from app.models import SearchRun, SearchRunStatus
    from app.services.run_service import fail_interrupted_runs

    db.add(SearchRun(trigger="manual", status=SearchRunStatus.RUNNING))
    db.add(SearchRun(trigger="manual", status=SearchRunStatus.COMPLETED))
    db.commit()
    assert fail_interrupted_runs(db) == 1
    statuses = sorted(r.status.value for r in db.query(SearchRun).all())
    assert statuses == ["COMPLETED", "FAILED"]
    assert fail_interrupted_runs(db) == 0


def test_start_of_today_uses_local_timezone():
    from datetime import timezone

    from app.services.dashboard_service import _start_of_today

    utc_midnight = _start_of_today(None)
    ist_midnight = _start_of_today("Asia/Kolkata")
    assert utc_midnight.tzinfo == timezone.utc and ist_midnight.tzinfo == timezone.utc
    # IST midnight is 18:30 UTC the previous day
    assert ist_midnight.hour == 18 and ist_midnight.minute == 30
    assert _start_of_today("Not/AZone") == utc_midnight
