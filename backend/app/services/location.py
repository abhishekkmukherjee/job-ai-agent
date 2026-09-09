"""Location priority: the order of the candidate's target locations is meaningful.

Rank 0 = first preferred city, ... , remote ranks after every listed city unless
"Remote" itself appears earlier in the list.  Unknown / other locations rank last.
"""
from __future__ import annotations

import re

from ..models import Job, Profile, RemoteType

# canonical name -> aliases (lower-case substrings)
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "bangalore": ("bangalore", "bengaluru", "blr"),
    "pune": ("pune",),
    "hyderabad": ("hyderabad", "secunderabad", "hyd"),
    "mumbai": ("mumbai", "bombay", "navi mumbai", "thane"),
    "delhi ncr": ("delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida", "faridabad", "ghaziabad"),
    "gurgaon": ("gurgaon", "gurugram"),
    "noida": ("noida",),
    "chennai": ("chennai", "madras"),
    "kolkata": ("kolkata", "calcutta"),
    "ahmedabad": ("ahmedabad",),
    "jaipur": ("jaipur",),
    "chandigarh": ("chandigarh", "mohali"),
    "kochi": ("kochi", "cochin", "trivandrum", "thiruvananthapuram"),
    "indore": ("indore",),
    "ranchi": ("ranchi",),
    "india": ("india", "in "),
    "remote": ("remote", "anywhere", "work from home", "wfh", "worldwide", "distributed"),
}


def _aliases(name: str) -> tuple[str, ...]:
    key = (name or "").strip().lower()
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    return (key,) if key else ()


def location_matches(job_location: str, preferred: str) -> bool:
    loc = (job_location or "").lower()
    return any(a and a in loc for a in _aliases(preferred))


def preferred_locations(profile: Profile) -> list[str]:
    seen: list[str] = []
    for loc in [*(profile.target_locations or []), *(profile.preferred_locations or [])]:
        if loc and loc.strip().lower() not in {s.lower() for s in seen}:
            seen.append(loc.strip())
    return seen


def location_rank(job: Job, profile: Profile) -> int:
    """Lower is better.  Cities in the profile's order, then remote, then everything else."""
    prefs = preferred_locations(profile)
    if not prefs:
        return 0
    remote_index = next((i for i, p in enumerate(prefs) if p.lower() == "remote"), None)
    is_remote = job.remote_type == RemoteType.REMOTE or location_matches(job.location, "remote")
    for i, pref in enumerate(prefs):
        if pref.lower() == "remote":
            continue
        if location_matches(job.location, pref):
            return i
    if is_remote:
        return remote_index if remote_index is not None else len(prefs)
    return len(prefs) + 1


def describe_priority(profile: Profile) -> str:
    prefs = preferred_locations(profile)
    if not prefs:
        return "no location preference"
    return " > ".join(prefs) + " (earlier is better)"


def is_indian_location(text: str) -> bool:
    t = (text or "").lower()
    return any(alias in t for name, aliases in CITY_ALIASES.items() if name not in ("remote",) for alias in aliases) or bool(re.search(r"\bindia\b", t))
