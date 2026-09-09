"""Rule-based job filtering (spec section 6) - cheap, deterministic, configurable.

Outcome per job:
    PASS    -> clearly relevant, goes to full AI analysis
    REJECT  -> clearly irrelevant, no LLM call at all
    UNSURE  -> rules could not decide; a cheap classification model decides next
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..models import Job, Profile, RemoteType
from ..schemas.settings import FilterRules


class FilterOutcome(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    UNSURE = "UNSURE"


@dataclass
class FilterResult:
    outcome: FilterOutcome
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    priority_hits: list[str] = field(default_factory=list)


# "3+ years", "3-5 years", "minimum of 5 years", "at least 4 yrs", "5 years of experience"
_YEARS_PATTERNS = [
    re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|to|–)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|year)", re.IGNORECASE),
    re.compile(r"(?:minimum|min\.?|at least|over|more than)\s*(?:of\s*)?(\d{1,2})\s*\+?\s*(?:years|yrs|year)", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*\+\s*(?:years|yrs|year)", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*(?:years|yrs|year)\s*(?:of\s*)?(?:\w+\s+){0,3}?(?:experience|exp)", re.IGNORECASE),
]


def extract_required_years(text: str) -> tuple[int | None, int | None]:
    """Return (min_years, max_years) mentioned in text, or (None, None)."""
    if not text:
        return None, None
    mins: list[int] = []
    maxs: list[int] = []
    for pat in _YEARS_PATTERNS:
        for m in pat.finditer(text):
            groups = [g for g in m.groups() if g]
            try:
                nums = [int(g) for g in groups]
            except ValueError:
                continue
            nums = [n for n in nums if 0 <= n <= 30]
            if not nums:
                continue
            if len(nums) == 2:
                mins.append(min(nums))
                maxs.append(max(nums))
            else:
                mins.append(nums[0])
    if not mins:
        return None, None
    # Postings list several requirements; the smallest minimum is the entry bar.
    return min(mins), (max(maxs) if maxs else None)


def _contains_keyword(text: str, keywords: list[str]) -> str | None:
    t = f" {text.lower()} "
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        # keywords that end with a space are word-prefix anchored (e.g. "vp ", "qa ")
        if k.endswith(" "):
            if f" {k}" in t or t.endswith(f" {k.strip()} "):
                return kw
        elif re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t):
            return kw
    return None


def _location_matches(job_location: str, preferred: list[str]) -> bool:
    from ..services.location import location_matches

    loc = (job_location or "").lower()
    if not loc:
        return False
    return any(p and p.strip().lower() != "remote" and location_matches(loc, p) for p in preferred)


_REGION_SPLIT = re.compile(r"[,/;|]|\band\b|\bor\b|\s-\s|\(|\)")
_UNRESTRICTED = {"remote", "", "fully remote", "remote work", "work from home", "wfh", "remote job"}


def remote_region_allowed(location: str, allowed_regions: list[str]) -> bool:
    """True when a remote posting is open to the candidate.

    An empty / generic location ("Remote") is unrestricted.  A location listing
    countries or regions is allowed only if one of them matches `allowed_regions`.
    """
    loc = (location or "").lower().strip()
    if loc in _UNRESTRICTED:
        return True
    parts = [p.strip(" .") for p in _REGION_SPLIT.split(loc) if p and p.strip(" .")]
    parts = [p for p in parts if p not in _UNRESTRICTED and p not in ("only", "based", "timezone", "time zone")]
    if not parts:
        return True
    allowed = [a.lower().strip() for a in allowed_regions if a and a.strip()]
    return any(any(a in part for a in allowed) for part in parts)


class RuleFilter:
    def __init__(self, rules: FilterRules):
        self.rules = rules

    def evaluate(self, job: Job, profile: Profile, now: datetime | None = None) -> FilterResult:
        rules = self.rules
        title = job.title or ""
        description = job.description or ""
        details: dict[str, Any] = {}

        # 1. hard title rejects (internships, wrong function, too senior, etc.)
        hit = _contains_keyword(title, rules.reject_title_keywords)
        if hit:
            return FilterResult(FilterOutcome.REJECT, f"title contains '{hit.strip()}'", {"rule": "reject_title_keyword", "keyword": hit})

        # 2. profile keyword rejects (title or description)
        hit = _contains_keyword(title, profile.keywords_reject or []) or _contains_keyword(description[:4000], profile.keywords_reject or [])
        if hit:
            return FilterResult(FilterOutcome.REJECT, f"matches rejected keyword '{hit}'", {"rule": "profile_keywords_reject", "keyword": hit})
        hit = _contains_keyword(description[:6000], rules.reject_description_keywords)
        if hit:
            return FilterResult(FilterOutcome.REJECT, f"description contains '{hit}'", {"rule": "reject_description_keyword", "keyword": hit})

        # 3. companies to avoid
        avoid = [c for c in [*(profile.companies_to_avoid or []), *rules.reject_companies] if c]
        company = (job.company or "").lower()
        for c in avoid:
            if c.lower().strip() and c.lower().strip() in company:
                return FilterResult(FilterOutcome.REJECT, f"company '{job.company}' is on the avoid list", {"rule": "company_avoid"})

        # 4. stale postings
        if rules.max_job_age_days and job.posted_at:
            now = now or datetime.now(timezone.utc)
            posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
            age = (now - posted).days
            details["age_days"] = age
            if age > rules.max_job_age_days:
                return FilterResult(FilterOutcome.REJECT, f"posted {age} days ago (limit {rules.max_job_age_days})", {"rule": "max_job_age", **details})

        # 5. experience requirement vs profile
        min_years, max_years = extract_required_years(description)
        details["required_years_min"] = min_years
        details["required_years_max"] = max_years
        if min_years is not None:
            ceiling = float(profile.years_of_experience or 0) + rules.max_experience_years_over_profile
            if min_years > ceiling:
                return FilterResult(
                    FilterOutcome.REJECT,
                    f"requires {min_years}+ years (profile has {profile.years_of_experience})",
                    {"rule": "experience_too_high", **details},
                )
            if max_years is not None and max_years < rules.min_experience_years_allowed:
                return FilterResult(FilterOutcome.REJECT, f"targets {max_years} years max (too junior)", {"rule": "experience_too_low", **details})

        # 6. onsite/hybrid roles outside preferred locations
        preferred = list(dict.fromkeys([*(profile.target_locations or []), *(profile.preferred_locations or [])]))
        wants_remote = profile.remote_preference in ("remote", "any", "hybrid") or "remote" in [p.lower() for p in preferred]
        if rules.reject_if_onsite_outside_preferred_locations and job.remote_type in (RemoteType.ONSITE, RemoteType.HYBRID):
            if preferred and not _location_matches(job.location, preferred):
                return FilterResult(
                    FilterOutcome.REJECT,
                    f"{job.remote_type.value} role in '{job.location}' outside preferred locations",
                    {"rule": "location", "preferred": preferred, **details},
                )
        if (
            rules.treat_unknown_work_mode_as_onsite
            and job.remote_type == RemoteType.UNKNOWN
            and (job.location or "").strip()
            and preferred
            and not _location_matches(job.location, preferred)
            and not remote_region_allowed(job.location, rules.allowed_remote_regions)
        ):
            return FilterResult(
                FilterOutcome.REJECT,
                f"location '{job.location}' outside preferred locations (work mode not stated)",
                {"rule": "location_unknown_mode", "preferred": preferred, **details},
            )
        if job.remote_type == RemoteType.REMOTE and not wants_remote:
            return FilterResult(FilterOutcome.REJECT, "remote role but profile wants onsite", {"rule": "remote_not_wanted", **details})
        if (
            rules.reject_remote_outside_regions
            and job.remote_type == RemoteType.REMOTE
            and not remote_region_allowed(job.location, rules.allowed_remote_regions)
        ):
            return FilterResult(
                FilterOutcome.REJECT,
                f"remote role restricted to '{job.location}'",
                {"rule": "remote_region", "allowed_regions": rules.allowed_remote_regions, **details},
            )

        # 7. role relevance from the title
        role_hit = _contains_keyword(title, rules.role_keywords) or _contains_keyword(title, profile.target_roles or [])
        priority_hits = [
            kw for kw in [*(profile.keywords_prioritize or []), *rules.prioritize_keywords]
            if kw and _contains_keyword(title + " " + description[:4000], [kw])
        ]
        details["role_keyword"] = role_hit
        details["priority_hits"] = priority_hits
        if role_hit:
            return FilterResult(FilterOutcome.PASS, f"title matches '{role_hit}'", details, priority_hits)

        # Title unknown: engineering-ish words in title + prioritized keywords in the body -> unsure
        generic = _contains_keyword(title, ["engineer", "developer", "programmer", "scientist", "architect", "sde"])
        if generic and priority_hits:
            return FilterResult(FilterOutcome.UNSURE, f"generic title '{title}' with relevant keywords", details, priority_hits)
        if generic:
            mode = rules.treat_unknown_title_as
            if mode == "pass":
                return FilterResult(FilterOutcome.PASS, "generic engineering title", details, priority_hits)
            if mode == "reject":
                return FilterResult(FilterOutcome.REJECT, "title does not match target roles", {"rule": "role_mismatch", **details})
            return FilterResult(FilterOutcome.UNSURE, f"generic title '{title}'", details, priority_hits)
        return FilterResult(FilterOutcome.REJECT, "title unrelated to target roles", {"rule": "role_mismatch", **details})
