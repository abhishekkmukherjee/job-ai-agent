from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.jobs.filters import FilterOutcome, RuleFilter, extract_required_years, remote_region_allowed
from app.models import Job, Profile, RemoteType
from app.schemas.settings import FilterRules


def profile_of(db) -> Profile:
    return db.execute(select(Profile)).scalars().one()


def job(title, description="", location="Bangalore", remote=RemoteType.UNKNOWN, company="Acme", days_old=1) -> Job:
    return Job(
        external_id="x", source="test", title=title, description=description, location=location, remote_type=remote,
        company=company, posted_at=datetime.now(timezone.utc) - timedelta(days=days_old),
    )


def test_extract_required_years():
    assert extract_required_years("We need 3+ years of Python experience") == (3, None)
    assert extract_required_years("2-5 years experience in backend") == (2, 5)
    assert extract_required_years("Minimum of 7 years") == (7, None)
    assert extract_required_years("at least 4 yrs of experience") == (4, None)
    assert extract_required_years("5 years of hands-on experience; 2+ years with LLMs") == (2, None)
    assert extract_required_years("no experience mentioned") == (None, None)


def test_rejects_internship_and_senior_titles(db):
    f = RuleFilter(FilterRules())
    p = profile_of(db)
    assert f.evaluate(job("Machine Learning Intern"), p).outcome == FilterOutcome.REJECT
    assert f.evaluate(job("VP Engineering"), p).outcome == FilterOutcome.REJECT
    assert f.evaluate(job("Principal AI Engineer"), p).outcome == FilterOutcome.REJECT
    assert f.evaluate(job("Product Manager, AI"), p).outcome == FilterOutcome.REJECT


def test_passes_target_roles(db):
    f = RuleFilter(FilterRules())
    p = profile_of(db)
    for title in ["AI Engineer", "Generative AI Engineer", "Machine Learning Engineer", "Backend Engineer - Python", "Full-Stack Engineer", "Software Engineer, AI Platform"]:
        r = f.evaluate(job(title, "Python, LLM, RAG on AWS", remote=RemoteType.REMOTE, location="Remote"), p)
        assert r.outcome == FilterOutcome.PASS, (title, r.reason)


def test_rejects_too_much_experience(db):
    f = RuleFilter(FilterRules())
    p = profile_of(db)  # 3 years, +3 allowed -> ceiling 6
    r = f.evaluate(job("Machine Learning Engineer", "We need 7+ years of experience"), p)
    assert r.outcome == FilterOutcome.REJECT and "7+" in r.reason
    r = f.evaluate(job("Machine Learning Engineer", "2-4 years of experience"), p)
    assert r.outcome == FilterOutcome.PASS
    assert r.details["required_years_min"] == 2


def test_rejects_onsite_outside_preferred_locations(db):
    f = RuleFilter(FilterRules())
    p = profile_of(db)  # Bangalore / Remote
    assert f.evaluate(job("Software Engineer", location="Pune, India", remote=RemoteType.ONSITE), p).outcome == FilterOutcome.REJECT
    assert f.evaluate(job("Software Engineer", location="Bengaluru", remote=RemoteType.ONSITE), p).outcome == FilterOutcome.PASS
    assert f.evaluate(job("Software Engineer", location="Bangalore, India (Hybrid)", remote=RemoteType.HYBRID), p).outcome == FilterOutcome.PASS
    assert f.evaluate(job("Software Engineer", location="Remote", remote=RemoteType.REMOTE), p).outcome == FilterOutcome.PASS
    f2 = RuleFilter(FilterRules(reject_if_onsite_outside_preferred_locations=False))
    assert f2.evaluate(job("Software Engineer", location="Pune", remote=RemoteType.ONSITE), p).outcome == FilterOutcome.PASS


def test_rejects_stale_and_avoided_companies_and_keywords(db):
    f = RuleFilter(FilterRules(max_job_age_days=30))
    p = profile_of(db)
    assert f.evaluate(job("AI Engineer", days_old=45), p).details["rule"] == "max_job_age"
    p.companies_to_avoid = ["Evil Corp"]
    assert f.evaluate(job("AI Engineer", company="Evil Corp Ltd"), p).details["rule"] == "company_avoid"
    assert f.evaluate(job("AI Engineer", "This is an unpaid position"), p).details["rule"] == "profile_keywords_reject"


def test_unsure_for_generic_titles_and_configurable(db):
    p = profile_of(db)
    r = RuleFilter(FilterRules()).evaluate(job("Engineer II", "Work on LLM and RAG systems with Python"), p)
    assert r.outcome == FilterOutcome.UNSURE and "LLM" in r.priority_hits
    assert RuleFilter(FilterRules()).evaluate(job("Systems Engineer", "networking"), p).outcome == FilterOutcome.UNSURE
    assert RuleFilter(FilterRules(treat_unknown_title_as="reject")).evaluate(job("Systems Engineer", "networking"), p).outcome == FilterOutcome.REJECT
    assert RuleFilter(FilterRules(treat_unknown_title_as="pass")).evaluate(job("Systems Engineer", "networking"), p).outcome == FilterOutcome.PASS
    assert RuleFilter(FilterRules()).evaluate(job("Office Administrator"), p).outcome == FilterOutcome.REJECT


def test_sample_jobs_filter_as_expected(db):
    f = RuleFilter(FilterRules())
    p = profile_of(db)
    outcomes = {j.company: f.evaluate(j, p).outcome for j in db.execute(select(Job)).scalars().all()}
    assert outcomes["Nimbus Labs"] == FilterOutcome.PASS
    assert outcomes["Orbital Health"] == FilterOutcome.PASS
    assert outcomes["Ledgerly"] == FilterOutcome.PASS
    assert outcomes["Brightpath"] == FilterOutcome.PASS
    assert outcomes["Quantiva"] == FilterOutcome.REJECT      # senior, 7+ years
    assert outcomes["DataSprout"] == FilterOutcome.REJECT    # intern
    assert outcomes["Helix Systems"] == FilterOutcome.REJECT  # onsite Pune


def test_remote_region_rule(db):
    allowed = FilterRules().allowed_remote_regions
    assert remote_region_allowed("Remote", allowed)
    assert remote_region_allowed("", allowed)
    assert remote_region_allowed("Remote - Worldwide", allowed)
    assert remote_region_allowed("Anywhere", allowed)
    assert remote_region_allowed("Remote (India)", allowed)
    assert remote_region_allowed("APAC / EMEA", allowed)
    assert not remote_region_allowed("USA", allowed)
    assert not remote_region_allowed("Canada, USA", allowed)
    assert not remote_region_allowed("France, Germany, Italy, Netherlands", allowed)
    assert not remote_region_allowed("Remote - EMEA only", allowed)
    f = RuleFilter(FilterRules())
    p = profile_of(db)
    r = f.evaluate(job("AI Engineer", location="USA", remote=RemoteType.REMOTE), p)
    assert r.outcome == FilterOutcome.REJECT and r.details["rule"] == "remote_region"
    assert f.evaluate(job("AI Engineer", location="Remote - Worldwide", remote=RemoteType.REMOTE), p).outcome == FilterOutcome.PASS
    f2 = RuleFilter(FilterRules(reject_remote_outside_regions=False))
    assert f2.evaluate(job("AI Engineer", location="USA", remote=RemoteType.REMOTE), p).outcome == FilterOutcome.PASS


def test_unknown_work_mode_outside_locations(db):
    p = profile_of(db)
    f = RuleFilter(FilterRules())
    r = f.evaluate(job("Backend Engineer - Golang", location="Berlin", remote=RemoteType.UNKNOWN), p)
    assert r.outcome == FilterOutcome.REJECT and r.details["rule"] == "location_unknown_mode"
    assert f.evaluate(job("Backend Engineer", location="Bangalore, Karnataka", remote=RemoteType.UNKNOWN), p).outcome == FilterOutcome.PASS
    assert f.evaluate(job("Backend Engineer", location="Remote - India", remote=RemoteType.UNKNOWN), p).outcome == FilterOutcome.PASS
    assert f.evaluate(job("Backend Engineer", location="", remote=RemoteType.UNKNOWN), p).outcome == FilterOutcome.PASS
    f2 = RuleFilter(FilterRules(treat_unknown_work_mode_as_onsite=False))
    assert f2.evaluate(job("Backend Engineer - Golang", location="Berlin", remote=RemoteType.UNKNOWN), p).outcome == FilterOutcome.PASS
