"""Deterministic mapping of application-form fields to profile data.

No LLM is involved here: labels, names, ids, placeholders and autocomplete hints
are matched against keyword rules.  Anything that is not clearly safe to fill
(EEO questions, legal identifiers, ambiguous selects) is left for the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import Profile


@dataclass
class FormField:
    selector: str
    kind: str                     # text|email|tel|url|number|textarea|select|file|checkbox|radio|date|password|...
    label: str = ""
    name: str = ""
    id: str = ""
    placeholder: str = ""
    aria_label: str = ""
    autocomplete: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = False
    value: str = ""
    accept: str = ""
    maxlength: int | None = None
    frame: int = 0

    @property
    def text(self) -> str:
        return " ".join(x for x in [self.label, self.name, self.id, self.placeholder, self.aria_label, self.autocomplete] if x).lower()

    @property
    def display(self) -> str:
        return self.label or self.placeholder or self.aria_label or self.name or self.id or self.selector

    @classmethod
    def from_dict(cls, d: dict[str, Any], frame: int = 0) -> "FormField":
        return cls(
            selector=d.get("selector", ""), kind=(d.get("kind") or "text").lower(), label=d.get("label", "") or "",
            name=d.get("name", "") or "", id=d.get("id", "") or "", placeholder=d.get("placeholder", "") or "",
            aria_label=d.get("aria_label", "") or "", autocomplete=d.get("autocomplete", "") or "",
            options=[o for o in (d.get("options") or []) if isinstance(o, str)], required=bool(d.get("required")),
            value=str(d.get("value") or ""), accept=d.get("accept", "") or "", maxlength=d.get("maxlength"), frame=frame,
        )


@dataclass
class FillAction:
    field: FormField
    action: str          # fill|select|upload|check|answer
    value: str
    source: str          # profile attribute / "answer" / "resume" / "consent"
    status: str = "planned"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.field.label or self.field.name or self.field.id or self.field.selector,
            "selector": self.field.selector, "kind": self.field.kind, "action": self.action,
            "value": self.value if self.action != "upload" else self.value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "source": self.source, "status": self.status, "note": self.note, "required": self.field.required,
        }


def _has(text: str, *words: str) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) for w in words)


# Order matters: the first matching rule wins.
_SKIP_PATTERNS = (
    "password", "confirm", "captcha", "gender", "race", "ethnic", "veteran", "disability", "religion", "sexual",
    "date of birth", "dob", "age", "marital", "caste", "aadhaar", "passport", "ssn", "social security",
    "credit card", "otp", "verification code",
)
_CONSENT_WORDS = ("agree", "consent", "privacy", "terms", "accept", "acknowledge", "confirm that", "i certify", "gdpr")
_MARKETING_WORDS = ("marketing", "newsletter", "promotional", "subscribe", "updates about", "talent community", "future opportunities")


def _split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _choose_option(options: list[str], candidates: list[str]) -> str | None:
    usable = [o for o in options if o and not re.match(r"^(select|choose|please|--|-)", o.strip().lower())]
    for cand in candidates:
        c = (cand or "").strip().lower()
        if not c:
            continue
        for o in usable:
            if c == o.strip().lower():
                return o
        for o in usable:
            if c in o.lower() or o.lower() in c:
                return o
    return None


def _notice_candidates(notice: str) -> list[str]:
    n = (notice or "").lower()
    cands = [notice]
    m = re.search(r"(\d+)", n)
    if m:
        cands.append(m.group(1))
        days = int(m.group(1))
        if "month" in n:
            cands.append(str(days * 30))
        if "week" in n:
            cands.append(str(days * 7))
    if any(w in n for w in ("immediate", "asap", "0 ", "none")):
        cands.append("immediate")
    return cands


def _years_candidates(years: float) -> list[str]:
    y = int(years)
    return [f"{y}-", f"{y} ", str(y), f"{y}+", f"{max(y - 1, 0)}-{y + 1}", f"{max(y - 2, 0)}-{y + 2}"]


def _lpa(amount: int | float) -> str:
    return f"{float(amount) / 100000.0:g} LPA"


def salary_value(profile: Profile, job_remote_type: str | None, numeric: bool, current: bool = False) -> str:
    """Salary figure for a form field, chosen by the job's work mode."""
    cur = (profile.salary_currency or "INR").upper()
    if current:
        if profile.current_salary:
            return str(int(profile.current_salary)) if numeric else f"{_lpa(profile.current_salary)} ({cur})"
        return ""
    remote = (job_remote_type or "").lower() == "remote"
    amount = profile.salary_expectation_remote if remote else profile.salary_expectation_onsite
    amount = amount or profile.salary_expectation_onsite or profile.salary_expectation_remote or profile.minimum_salary
    if amount:
        return str(int(amount)) if numeric else f"{_lpa(amount)} ({cur})"
    return "" if numeric else (profile.expected_salary or "")


def looks_like_question(f: FormField) -> bool:
    t = (f.label or f.placeholder or f.aria_label or "").strip()
    if not t:
        return False
    tl = t.lower()
    return (
        t.endswith("?")
        or tl.startswith(("why", "what", "tell", "describe", "how", "explain", "share", "please describe"))
        or _has(tl, "cover letter", "motivation", "about yourself", "additional information", "anything else", "message")
    )


def map_fields(
    fields: list[FormField], profile: Profile, resume_path: str | None, cover_note: str = "", job_remote_type: str | None = None
) -> tuple[list[FillAction], list[FormField], list[FormField]]:
    """Return (actions, question_fields, unmatched_fields)."""
    actions: list[FillAction] = []
    questions: list[FormField] = []
    unmatched: list[FormField] = []
    first, last = _split_name(profile.full_name)
    resume_uploaded = False

    for f in fields:
        t = f.text
        kind = f.kind
        if kind in ("hidden", "submit", "button", "reset", "image", "password"):
            continue
        if _has(t, *_SKIP_PATTERNS):
            unmatched.append(f)
            continue

        if kind == "file":
            if resume_path and not resume_uploaded and (
                _has(t, "resume", "cv", "curriculum") or "pdf" in f.accept.lower() or not t.strip()
            ):
                actions.append(FillAction(f, "upload", resume_path, "resume"))
                resume_uploaded = True
            else:
                unmatched.append(f)
            continue

        if kind == "checkbox":
            # Privacy / terms consent is required to submit at all; marketing opt-ins and EEO boxes stay untouched.
            if _has(t, *_CONSENT_WORDS) and not _has(t, *_MARKETING_WORDS):
                actions.append(FillAction(f, "check", "yes", "consent"))
            else:
                unmatched.append(f)
            continue
        if kind == "radio":
            unmatched.append(f)  # yes/no and EEO questions stay with the user
            continue

        if kind == "select":
            value = None
            if _has(t, "notice"):
                value = _choose_option(f.options, _notice_candidates(profile.notice_period))
            elif _has(t, "experience", "years"):
                value = _choose_option(f.options, _years_candidates(profile.years_of_experience or 0))
            elif _has(t, "country"):
                value = _choose_option(f.options, ["India"] if "india" in (profile.current_location or "").lower() else [profile.current_location])
            elif _has(t, "location", "city", "office"):
                value = _choose_option(f.options, [profile.current_location, *profile.preferred_locations])
            elif _has(t, "remote", "work mode", "workplace"):
                value = _choose_option(f.options, [profile.remote_preference] if profile.remote_preference != "any" else [])
            elif _has(t, "authoriz", "eligible to work", "legally") and (profile.work_authorization or ""):
                value = _choose_option(f.options, ["yes"])
            elif _has(t, "source", "hear about", "how did you"):
                value = _choose_option(f.options, ["job board", "other", "website", "online"])
            if value:
                actions.append(FillAction(f, "select", value, "profile"))
            else:
                unmatched.append(f)
            continue

        if kind == "textarea" or (kind == "text" and looks_like_question(f) and (f.maxlength is None or f.maxlength > 120)):
            if _has(t, "cover letter") and cover_note:
                actions.append(FillAction(f, "fill", cover_note, "cover_note"))
            elif looks_like_question(f) or kind == "textarea":
                questions.append(f)
            else:
                unmatched.append(f)
            continue

        # plain inputs -------------------------------------------------------
        value: str | None = None
        source = "profile"
        numeric = kind == "number"
        if kind == "email" or _has(t, "email", "e-mail") or f.autocomplete == "email":
            value = profile.email
        elif kind == "tel" or _has(t, "phone", "mobile", "contact number", "telephone", "whatsapp") or f.autocomplete == "tel":
            value = profile.phone
        elif _has(t, "first name", "given name", "firstname") or f.autocomplete == "given-name":
            value = first
        elif _has(t, "last name", "surname", "family name", "lastname") or f.autocomplete == "family-name":
            value = last
        elif _has(t, "full name", "your name", "candidate name", "applicant name") or f.autocomplete == "name" or (t.strip() == "name") or (_has(t, "name") and not _has(t, "company", "employer", "user", "file", "school", "college", "reference")):
            value = profile.full_name
        elif _has(t, "linkedin"):
            value = profile.linkedin_url
        elif _has(t, "github"):
            value = profile.github_url
        elif _has(t, "portfolio", "website", "personal site", "homepage", "url") and kind in ("url", "text"):
            value = profile.portfolio_url or profile.github_url
        elif _has(t, "notice"):
            value = profile.notice_period
        elif _has(t, "current salary", "current ctc", "present salary", "current compensation", "current pay"):
            value = salary_value(profile, job_remote_type, numeric, current=True)
            source = "salary"
        elif _has(t, "salary", "ctc", "compensation", "pay expectation", "expected pay"):
            value = salary_value(profile, job_remote_type, numeric)
            source = "salary"
        elif _has(t, "current company", "employer", "current organization", "organisation", "company name"):
            value = profile.current_company
        elif _has(t, "current title", "current role", "designation", "job title", "current position"):
            value = profile.current_role
        elif _has(t, "experience", "years") and kind in ("number", "text"):
            years = profile.years_of_experience or 0
            value = str(int(years)) if float(years).is_integer() else str(years)
        elif _has(t, "location", "city", "address", "where are you based", "current place"):
            value = profile.current_location
        elif _has(t, "authoriz", "visa", "sponsorship", "work permit") and kind == "text":
            value = profile.work_authorization
        elif _has(t, "skills", "technologies"):
            value = ", ".join((profile.skills or [])[:15])
        if value is None:
            unmatched.append(f)
        elif not str(value).strip():
            actions.append(FillAction(f, "fill", "", source, status="skipped", note="no value in profile"))
        else:
            if f.maxlength and len(str(value)) > f.maxlength:
                value = str(value)[: f.maxlength]
            actions.append(FillAction(f, "fill", str(value), source))
    return actions, questions, unmatched


def match_existing_answer(question: str, answers: list[dict[str, Any]]) -> dict[str, Any] | None:
    q = re.sub(r"[^a-z0-9 ]+", " ", question.lower()).strip()
    if not q:
        return None
    best = None
    best_score = 0.0
    q_tokens = set(q.split())
    for a in answers:
        aq = re.sub(r"[^a-z0-9 ]+", " ", str(a.get("question", "")).lower()).strip()
        if not aq or not a.get("answer"):
            continue
        if aq == q or aq in q or q in aq:
            return a
        a_tokens = set(aq.split())
        overlap = len(q_tokens & a_tokens) / max(1, len(q_tokens | a_tokens))
        if overlap > best_score:
            best, best_score = a, overlap
    return best if best_score >= 0.5 else None


def submit_blockers(
    actions: list[FillAction], unmatched: list[FormField], submits: list[str], captcha: bool, fields_total: int
) -> list[str]:
    """Reasons why a filled form must NOT be submitted automatically.  Empty list = safe."""
    blockers: list[str] = []
    if fields_total == 0:
        blockers.append("no form fields found on the page")
    if captcha:
        blockers.append("CAPTCHA present (never bypassed)")
    if not submits:
        blockers.append("no submit button found")
    # The form must look like a job application, not a newsletter box or a search bar:
    # an identity field (name/email) plus either a resume upload or several profile fields.
    filled = [a for a in actions if a.status in ("filled", "uploaded")]
    identity = any(a.source == "profile" and a.field.kind in ("email", "text") and _has(a.field.text, "email", "e-mail", "name") for a in filled)
    uploaded = any(a.action == "upload" and a.status == "uploaded" for a in filled)
    profile_fields = sum(1 for a in filled if a.source in ("profile", "salary"))
    if fields_total and not (identity and (uploaded or profile_fields >= 3)):
        blockers.append("page does not look like an application form (no name/email with resume upload or profile fields)")
    for f in unmatched:
        if f.required:
            blockers.append(f"required field not filled: {f.display[:60]}")
    for a in actions:
        if a.status == "failed" and a.field.required:
            blockers.append(f"required field failed: {a.field.display[:60]}")
        if a.status == "skipped" and a.field.required:
            blockers.append(f"required field has no profile value: {a.field.display[:60]}")
    return blockers
