"""JSearch / Jooble connectors (mocked HTTP) and the job-alert email parser."""
from __future__ import annotations

from datetime import datetime, timezone

from app.jobs.sources.base import SearchContext
from app.jobs.sources.email_alerts import EmailAlertsSource, parse_alert_email
from app.jobs.sources.jooble import JoobleSource
from app.jobs.sources.jsearch import JSearchSource
from app.models import RemoteType

CTX = SearchContext(queries=["AI Engineer", "Backend Engineer"], locations=["Bangalore", "Remote"], remote_ok=True, max_results=50)


async def test_jsearch_maps_results(monkeypatch):
    src = JSearchSource(api_key="k", country="in", max_queries=2)
    calls = []

    async def fake_get(url, params=None, headers=None):
        calls.append((params["query"], params.get("work_from_home")))
        return {
            "data": [
                {
                    "job_id": "abc", "job_title": "AI Engineer", "employer_name": "Acme", "job_city": "Bengaluru", "job_state": "Karnataka",
                    "job_country": "IN", "job_is_remote": False, "job_description": "<p>Build LLM apps</p>", "job_apply_link": "https://in.linkedin.com/jobs/view/1",
                    "job_apply_is_direct": False, "job_publisher": "LinkedIn", "job_employment_type": "FULLTIME",
                    "job_posted_at_datetime_utc": "2026-09-08T10:00:00.000Z", "job_min_salary": 1200000, "job_max_salary": 1800000, "job_salary_currency": "INR",
                    "apply_options": [{"publisher": "LinkedIn", "apply_link": "https://in.linkedin.com/jobs/view/1"}, {"publisher": "Acme", "apply_link": "https://acme.com/careers/1"}],
                },
                {"job_id": "def", "job_title": "Sales Manager", "employer_name": "X"},
            ]
        }

    monkeypatch.setattr(src, "_get_json", fake_get)
    jobs = await src.fetch(CTX)
    assert [c[0] for c in calls] == ["AI Engineer in Bangalore", "AI Engineer remote"]
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Acme" and j.location == "Bengaluru, Karnataka, IN" and j.salary_max == 1800000 and j.salary_currency == "INR"
    assert j.description == "Build LLM apps" and j.posted_at == datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
    assert j.tags == ["LinkedIn", "FULLTIME"] and len(j.raw["apply_options"]) == 2
    assert src.is_configured(CTX) and not JSearchSource(api_key="").is_configured(CTX)


async def test_jooble_maps_results(monkeypatch):
    src = JoobleSource(api_key="k")

    async def fake_post(url, body):
        assert url.endswith("/api/k")
        return {"jobs": [{"id": 5, "title": "Backend Engineer (Python)", "location": "Bangalore", "snippet": "FastAPI &amp; AWS", "salary": "", "source": "company.com", "type": "Full-time", "link": "https://jooble.org/desc/5", "company": "Beta", "updated": "2026-09-07T00:00:00"}]}

    monkeypatch.setattr(src, "_post_json", fake_post)
    jobs = await src.fetch(SearchContext(queries=["Backend Engineer"], locations=["Bangalore"], max_results=10))
    assert len(jobs) == 1 and jobs[0].company == "Beta" and jobs[0].tags == ["Full-time", "company.com"]


LINKEDIN_HTML = """
<html><body>
<table><tr><td>
  <a href="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abc&refId=xyz">Senior AI Engineer</a>
  <p>Nimbus Labs · Bengaluru, Karnataka, India (Remote)</p>
  <p>Actively recruiting · 2 days ago</p>
  <a href="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=dup">View job</a>
</td></tr>
<tr><td>
  <a href="https://www.linkedin.com/jobs/view/backend-engineer-at-ledgerly-4987654321?refId=1">Backend Engineer</a>
  <p>Ledgerly</p><p>Bangalore Urban, Karnataka, India</p>
</td></tr></table>
<a href="https://www.linkedin.com/e/v2?e=abc&t=plh&midToken=1">Unsubscribe</a>
</body></html>
"""

NAUKRI_HTML = """
<div><a href="https://www.naukri.com/job-listings-ai-engineer-acme-technologies-bengaluru-3-to-6-years-090926501234?src=jobalert&sid=1">AI Engineer</a>
<span>Acme Technologies</span><span>Bengaluru, Hybrid</span><span>3-6 Yrs</span></div>
<div><a href="https://track.naukri.com/r?url=https%3A%2F%2Fwww.naukri.com%2Fjob-listings-ml-engineer-beta-pune-2-to-5-years-090926509999%3Fsrc%3Dalert">ML Engineer</a><span>Beta Corp</span><span>Pune</span></div>
"""

INDEED_HTML = """
<a href="https://in.indeed.com/rc/clk?jk=0a1b2c3d4e5f6789&from=ja&tk=1">Python Developer</a><div>Gamma Ltd - Remote in Bengaluru</div>
<a href="https://in.indeed.com/viewjob?jk=0a1b2c3d4e5f6789&from=ja">View</a>
"""


def test_parse_linkedin_alert():
    jobs = parse_alert_email(LINKEDIN_HTML, subject="AI Engineer: Nimbus Labs and 4 more", sender="jobalerts-noreply@linkedin.com")
    assert [j.external_id for j in jobs] == ["linkedin-4123456789", "linkedin-4987654321"]
    a, b = jobs
    assert a.title == "Senior AI Engineer" and a.company == "Nimbus Labs" and "Bengaluru" in a.location and a.remote_type == RemoteType.REMOTE
    assert a.url.startswith("https://www.linkedin.com/comm/jobs/view/4123456789")
    assert b.company == "Ledgerly" and b.location.startswith("Bangalore Urban")
    assert "linkedin" in a.tags and "job alert email" in a.description


def test_parse_naukri_and_indeed_alerts():
    naukri = parse_alert_email(NAUKRI_HTML, subject="Jobs for you", sender="info@naukri.com")
    assert [j.external_id for j in naukri] == ["naukri-090926501234", "naukri-090926509999"]
    assert naukri[0].company == "Acme Technologies" and naukri[0].remote_type == RemoteType.HYBRID
    assert naukri[1].url.startswith("https://www.naukri.com/job-listings-ml-engineer")  # tracking redirect unwrapped
    indeed = parse_alert_email(INDEED_HTML, subject="new jobs", sender="alert@indeed.com")
    assert len(indeed) == 1 and indeed[0].external_id == "indeed-0a1b2c3d4e5f6789" and indeed[0].title == "Python Developer"


async def test_email_source_filters_by_queries(monkeypatch):
    src = EmailAlertsSource(host="imap.example.com", user="u", password="p")
    monkeypatch.setattr(src, "_fetch_messages", lambda: [("subj", "jobalerts-noreply@linkedin.com", LINKEDIN_HTML, None), ("subj2", "info@naukri.com", NAUKRI_HTML, None)])
    jobs = await src.fetch(SearchContext(queries=["AI Engineer"], max_results=10))
    ids = {j.external_id for j in jobs}
    assert "linkedin-4123456789" in ids and "naukri-090926501234" in ids
    assert "linkedin-4987654321" in ids  # "Backend Engineer" passes the generic engineer/developer fallback
    assert not EmailAlertsSource().is_configured(SearchContext(queries=[]))


def test_parse_naukri_recruiter_broadcast():
    html = """<div><p>Dear Abhishek, we have an opening for Python Developer with Expertscan. Experience: 2-5 years. Location: Pune (Hybrid).</p>
    <a href="http://my.naukri.com/AL/ResdexRMJMail/alid/{}/redirectParam/applyBroadcastMail?xz=1">Apply now</a>
    <a href="https://www.naukri.com/imposter/report-fake-job-recruiter">block this recruiter</a></div>"""
    jobs = parse_alert_email(html, subject="✉️ Job | Python Developer in Pune", sender="Expertscan Consultant <recruiter@naukri.com>")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Python Developer" and j.location == "Pune" and j.company == "Expertscan Consultant"
    assert j.url.startswith("http://my.naukri.com/AL/ResdexRMJMail") and j.remote_type == RemoteType.HYBRID
    assert "recruiter-email" in j.tags and j.external_id.startswith("recruiter-")
    # marketing mail without a job subject yields nothing
    assert parse_alert_email("<a href='https://www.naukri.com/'>Explore</a>", subject="Top companies are hiring on Naukri right now!", sender="Naukri <info@naukri.com>") == []
