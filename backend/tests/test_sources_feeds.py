"""Y Combinator, Himalayas, We Work Remotely and HN Who-is-hiring connectors (mocked HTTP)."""
from __future__ import annotations

import html
import json
from xml.etree import ElementTree as ET

from app.jobs.sources.base import SearchContext
from app.jobs.sources.feeds import HimalayasSource, HNHiringSource, WeWorkRemotelySource, parse_hn_comment
from app.jobs.sources.ycombinator import YCombinatorSource, parse_job_postings
from app.models import RemoteType

CTX = SearchContext(queries=["AI Engineer", "Software Engineer", "Backend Engineer"], locations=["Bangalore", "Remote"], max_results=50)


def test_ycombinator_parses_embedded_json(monkeypatch):
    page = {"component": "WaasJobListingsPage", "props": {"jobPostings": [
        {"id": "1", "title": "Lead AI Engineer", "url": "/companies/vahan/jobs/7zv-lead-ai-engineer", "applyUrl": "https://account.ycombinator.com/authenticate?x", "location": "Bengaluru, KA, IN", "type": "Full-time", "prettyRole": "Software Engineer", "salaryRange": "₹30L - ₹50L INR", "minExperience": "3+ years", "skills": ["Python", "LLM"], "companyName": "Vahan", "companyBatchName": "W20", "companyOneLiner": "AI recruiter for blue collar jobs", "createdAt": "2 days"},
        {"id": "2", "title": "Account Executive", "url": "/companies/x/jobs/1-ae", "location": "Remote", "companyName": "X", "prettyRole": "Sales"},
    ]}}
    html_page = '<html><div id="app" data-page="' + html.escape(json.dumps(page), quote=True) + '"></div></html>'
    assert len(parse_job_postings(html_page)) == 2
    src = YCombinatorSource()
    calls = []

    async def fake_get_html(path):
        calls.append(path)
        return html_page

    monkeypatch.setattr(src, "_get_html", fake_get_html)
    import asyncio

    jobs = asyncio.run(src.fetch(CTX))
    assert len(jobs) == 1 and jobs[0].company == "Vahan" and jobs[0].url == "https://www.ycombinator.com/companies/vahan/jobs/7zv-lead-ai-engineer"
    assert "Bengaluru" in jobs[0].location and "3+ years" in jobs[0].description and "W20" in jobs[0].tags
    assert len(calls) >= 1


async def test_himalayas_maps_and_paginates(monkeypatch):
    src = HimalayasSource()
    pages = [
        {"nextCursor": "c2", "jobs": [{"guid": "g1", "title": "Senior Backend Engineer", "companyName": "Alpha", "locationRestrictions": ["India", "Singapore"], "description": "<p>Go and Python</p>", "applicationLink": "https://himalayas.app/companies/alpha/jobs/1", "pubDate": "1788983986", "seniority": ["Senior"], "categories": ["Backend"], "minSalary": "40000", "maxSalary": "60000", "currency": "USD", "salaryPeriod": "year", "employmentType": "Full-time"}]},
        {"nextCursor": None, "jobs": [{"guid": "g2", "title": "AI Engineer", "companyName": "Beta", "locationRestrictions": [], "description": "LLM apps", "applicationLink": "https://b.example/apply", "pubDate": "1788983986", "salaryPeriod": "hour", "minSalary": "40"}]},
    ]

    async def fake_get(url, params=None, headers=None):
        return pages.pop(0)

    monkeypatch.setattr(src, "_get_json", fake_get)
    jobs = await src.fetch(CTX)
    assert [j.company for j in jobs] == ["Alpha", "Beta"]
    assert jobs[0].location == "Remote (India, Singapore)" and jobs[0].salary_max == 60000 and jobs[0].remote_type == RemoteType.REMOTE
    assert jobs[1].location == "Remote - Worldwide" and jobs[1].salary_min is None  # hourly rate not treated as annual salary


def test_wwr_parses_rss():
    rss = """<?xml version="1.0"?><rss><channel>
      <item><title>Zeta: Senior Software Engineer (Python)</title><region>Anywhere in the World</region><category>Back-End Programming</category>
        <description>&lt;p&gt;Build APIs&lt;/p&gt;</description><pubDate>Tue, 18 Aug 2026 20:32:19 +0000</pubDate><guid>https://weworkremotely.com/remote-jobs/zeta-1</guid><link>https://weworkremotely.com/remote-jobs/zeta-1</link></item>
      <item><title>Acme: Product Designer</title><link>https://weworkremotely.com/remote-jobs/acme-2</link></item>
    </channel></rss>"""
    src = WeWorkRemotelySource()
    jobs = src.parse_feed(ET.fromstring(rss), CTX, set())
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Zeta" and j.title == "Senior Software Engineer (Python)" and j.description == "Build APIs"
    assert j.location == "Remote (Anywhere in the World)" and j.posted_at is not None and j.tags == ["Back-End Programming"]


def test_hn_comment_parsing():
    c = {"id": 123, "created_at": "2026-09-02T10:00:00.000Z", "text": "Modash.io | Senior Backend Engineer | Remote (India, Europe) | Full-time | &#8364;75k&#x2013;110k<p>We build creator tools. Email jobs@modash.io with your CV.</p>"}
    job = parse_hn_comment(c, CTX)
    assert job is not None
    assert job.company == "Modash.io" and job.title == "Senior Backend Engineer" and job.location.startswith("Remote (India")
    assert job.url.endswith("item?id=123") and job.remote_type == RemoteType.REMOTE and "jobs@modash.io" in job.description
    assert parse_hn_comment({"id": 1, "text": "Just a comment without pipes"}, CTX) is None
    assert parse_hn_comment({"id": 2, "text": "Acme | Sales Lead | Remote"}, CTX) is None


async def test_hn_source_uses_latest_thread(monkeypatch):
    src = HNHiringSource()
    calls = []

    async def fake_get(url, params=None, headers=None):
        calls.append(url)
        if "search_by_date" in url:
            return {"hits": [{"objectID": "900", "title": "Ask HN: Who wants to be hired? (September 2026)"}, {"objectID": "901", "title": "Ask HN: Who is hiring? (September 2026)"}]}
        assert url.endswith("/901")
        return {"children": [{"id": 5, "text": "Nimbus | AI Engineer | Bangalore, India | Onsite | INR 25-35 LPA"}, {"id": 6, "text": None}]}

    monkeypatch.setattr(src, "_get_json", fake_get)
    jobs = await src.fetch(CTX)
    assert len(jobs) == 1 and jobs[0].company == "Nimbus" and jobs[0].location == "Bangalore, India"
