from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.jobs.dedupe import content_hash, find_duplicate, normalize_company, normalize_title, normalize_url
from app.jobs.normalize import clean_text, html_to_text, infer_remote_type, parse_datetime, to_float
from app.models import Job, RemoteType
from app.schemas.job import NormalizedJob


def test_html_to_text_strips_markup_and_scripts():
    html = "<h2>Role</h2><p>We need <b>Python</b>.</p><ul><li>RAG</li><li>AWS</li></ul><script>alert(1)</script>"
    text = html_to_text(html)
    assert "alert" not in text and "<" not in text
    assert "Role" in text and "- RAG" in text and "- AWS" in text


def test_clean_text_collapses_whitespace():
    assert clean_text("a   b \n\n\n\n c\xa0d") == "a b\n\nc d"


def test_parse_datetime_formats():
    assert parse_datetime("2026-09-01T10:00:00Z") == datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    assert parse_datetime("2026-09-01") == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert parse_datetime(1756720000) == datetime.fromtimestamp(1756720000, tz=timezone.utc)
    assert parse_datetime(1756720000000).year == 2025
    assert parse_datetime("garbage") is None
    assert parse_datetime(None) is None


def test_infer_remote_type():
    assert infer_remote_type("Remote - Worldwide") == RemoteType.REMOTE
    assert infer_remote_type("Bangalore (Hybrid)") == RemoteType.HYBRID
    assert infer_remote_type("Pune, onsite") == RemoteType.ONSITE
    assert infer_remote_type("Pune") == RemoteType.UNKNOWN
    assert infer_remote_type("Pune", default=RemoteType.ONSITE) == RemoteType.ONSITE


def test_to_float():
    assert to_float("1,20,000") == 120000.0
    assert to_float("") is None and to_float("x") is None and to_float(-5) is None


def test_normalized_job_requires_title_and_id():
    with pytest.raises(ValidationError):
        NormalizedJob(external_id="", source="x", title="Dev")
    with pytest.raises(ValidationError):
        NormalizedJob(external_id="1", source="x", title="   ")
    nj = NormalizedJob(external_id=" 42 ", source="x", title=" Dev ")
    assert nj.external_id == "42" and nj.title == "Dev" and nj.remote_type == RemoteType.UNKNOWN


def test_normalizers():
    assert normalize_title("Senior AI Engineer (LLM) - II") == normalize_title("AI Engineer LLM")
    assert normalize_company("Nimbus Labs Pvt. Ltd.") == "nimbus"
    assert normalize_url("https://Example.com/jobs/1/?utm_source=x#top") == "https://example.com/jobs/1"
    assert normalize_url("https://news.ycombinator.com/item?id=123") != normalize_url("https://news.ycombinator.com/item?id=124")
    assert normalize_url("https://in.indeed.com/viewjob?jk=abc&from=ja&tk=1") == "https://in.indeed.com/viewjob?jk=abc"
    assert content_hash("AI Engineer", "Nimbus Labs") == content_hash("Sr. AI Engineer", "nimbus labs inc")


def test_find_duplicate_by_external_id_url_and_content(db):
    sample = db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()
    assert find_duplicate(db, source="sample", external_id=sample.external_id, title="x", company="y", url="").id == sample.id
    assert find_duplicate(db, source="remotive", external_id="999", title="x", company="y", url=sample.url + "/").id == sample.id
    assert find_duplicate(db, source="remotive", external_id="999", title="Senior AI Engineer (LLM Applications)", company="Nimbus Labs Inc", url="").id == sample.id
    assert find_duplicate(db, source="remotive", external_id="999", title="Data Engineer", company="Other Co", url="") is None
