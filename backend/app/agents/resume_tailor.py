"""Resume tailoring (spec section 8).

The model may reorder, select, rephrase and emphasise - but every fact must come
from the master profile.  After generation, `ground_resume` removes anything that
cannot be traced back to the profile (unknown skills, companies, projects,
certifications, or bullets containing numbers that the profile never mentions).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..ai.base import AIUnavailableError
from ..ai.cache import AIResultCache, job_hash_for
from ..ai.prompts import load_prompt, render_prompt
from ..ai.router import AIRouter
from ..config import Settings
from ..logging_config import log_event
from ..models import Application, ApplicationStatus, Job, Profile
from ..schemas.ai import TailoredResume
from ..schemas.application import ApplicationCreate
from ..services import application_service
from ..services.profile_service import get_profile, profile_to_json
from ..services.resume_pdf import render_resume_pdf, resume_path_for
from .job_analyzer import SYSTEM_PROMPT, job_to_prompt_text

TASK = "resume_tailoring"
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%?|\b(?:million|billion|thousand)\b", re.IGNORECASE)


class TailoringFailed(Exception):
    pass


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _profile_corpus(profile: Profile) -> str:
    parts = [profile.summary or "", " ".join(profile.skills or []), " ".join(profile.technologies or [])]
    for exp in profile.experience or []:
        parts.append(f"{exp.get('title', '')} {exp.get('company', '')} {exp.get('start', '')} {exp.get('end', '')}")
        parts.extend(exp.get("bullets") or [])
        parts.extend(exp.get("technologies") or [])
    for proj in profile.projects or []:
        parts.append(f"{proj.get('name', '')} {proj.get('description', '')}")
        parts.extend(proj.get("bullets") or [])
        parts.extend(proj.get("technologies") or [])
    for edu in profile.education or []:
        parts.append(f"{edu.get('degree', '')} {edu.get('institution', '')} {edu.get('year', '')} {edu.get('details', '')}")
    parts.extend(profile.achievements or [])
    parts.extend(profile.certifications or [])
    parts.append(str(profile.years_of_experience))
    return " ".join(parts)


def _known_terms(profile: Profile) -> set[str]:
    terms: set[str] = set()
    for s in [*(profile.skills or []), *(profile.technologies or [])]:
        terms.add(_norm(s))
    for exp in profile.experience or []:
        terms.update(_norm(t) for t in (exp.get("technologies") or []))
    for proj in profile.projects or []:
        terms.update(_norm(t) for t in (proj.get("technologies") or []))
    return {t for t in terms if t}


def _term_supported(term: str, known: set[str], corpus_norm: str) -> bool:
    t = _norm(term)
    if not t:
        return False
    if t in known:
        return True
    if any(t in k or k in t for k in known if len(k) >= 3 and len(t) >= 3):
        return True
    return f" {t} " in f" {corpus_norm} "


def _numbers_supported(text: str, corpus: str) -> bool:
    for m in _NUMBER_RE.finditer(text):
        token = m.group(0).strip().lower()
        if token and token not in corpus.lower():
            return False
    return True


def ground_resume(resume: TailoredResume, profile: Profile) -> tuple[TailoredResume, list[str]]:
    """Strip anything not traceable to the master profile.  Returns (resume, removed_items)."""
    removed: list[str] = []
    corpus = _profile_corpus(profile)
    corpus_norm = _norm(corpus)
    known = _known_terms(profile)

    skills = []
    for s in resume.skills:
        if _term_supported(s, known, corpus_norm):
            skills.append(s)
        else:
            removed.append(f"skill '{s}'")
    resume.skills = list(dict.fromkeys(skills))

    profile_exps = profile.experience or []
    kept_exps = []
    for exp in resume.experience:
        match = None
        for pe in profile_exps:
            if _norm(pe.get("company", "")) == _norm(exp.company) or (
                _norm(pe.get("title", "")) == _norm(exp.title) and _norm(pe.get("company", "")) in _norm(exp.company)
            ):
                match = pe
                break
        if match is None:
            removed.append(f"experience '{exp.title} at {exp.company}'")
            continue
        exp.title = match.get("title") or exp.title
        exp.company = match.get("company") or exp.company
        exp.start = match.get("start") or ""
        exp.end = match.get("end") or ""
        bullets = []
        for b in exp.bullets:
            if _numbers_supported(b, corpus):
                bullets.append(b)
            else:
                removed.append(f"bullet with unsupported number: '{b[:60]}'")
        exp.bullets = bullets
        kept_exps.append(exp)
    resume.experience = kept_exps

    profile_projects = {_norm(p.get("name", "")): p for p in (profile.projects or [])}
    kept_projects = []
    for proj in resume.projects:
        pp = profile_projects.get(_norm(proj.name))
        if pp is None:
            candidates = [v for k, v in profile_projects.items() if k and (k in _norm(proj.name) or _norm(proj.name) in k)]
            pp = candidates[0] if candidates else None
        if pp is None:
            removed.append(f"project '{proj.name}'")
            continue
        proj.name = pp.get("name") or proj.name
        if not _numbers_supported(proj.description, corpus):
            proj.description = pp.get("description", "")
            removed.append(f"project description for '{proj.name}' replaced (unsupported number)")
        proj.technologies = [t for t in proj.technologies if _term_supported(t, known, corpus_norm)]
        kept_projects.append(proj)
    resume.projects = kept_projects

    # Education / certifications / achievements are rebuilt straight from the profile
    resume.education = [
        " - ".join(x for x in [e.get("degree", ""), e.get("institution", "")] if x) + (f" ({e['year']})" if e.get("year") else "")
        for e in (profile.education or [])
        if e.get("degree")
    ]
    certs_known = {_norm(c) for c in (profile.certifications or [])}
    dropped_certs = [c for c in resume.certifications if _norm(c) not in certs_known]
    removed.extend(f"certification '{c}'" for c in dropped_certs)
    resume.certifications = list(profile.certifications or [])
    ach_known = {_norm(a) for a in (profile.achievements or [])}
    dropped_ach = [a for a in resume.achievements if _norm(a) not in ach_known]
    removed.extend(f"achievement '{a}'" for a in dropped_ach)
    resume.achievements = list(profile.achievements or [])

    if not _numbers_supported(resume.summary, corpus):
        removed.append("summary contained an unsupported number; replaced with profile summary")
        resume.summary = profile.summary or ""
    if removed:
        resume.tailoring_notes = [*resume.tailoring_notes, f"Grounding check removed {len(removed)} unsupported item(s): " + "; ".join(removed[:6])]
    return resume, removed


class ResumeTailor:
    def __init__(self, ai_router: AIRouter, settings: Settings, cache: AIResultCache | None = None):
        self.ai = ai_router
        self.settings = settings
        self.cache = cache or AIResultCache()

    async def generate(self, db: Session, job: Job, profile: Profile | None = None, force: bool = False) -> tuple[TailoredResume, str]:
        """Return (grounded resume, model label)."""
        profile = profile or get_profile(db)
        job_hash = job_hash_for(job)
        version = self.settings.resume_tailoring_prompt_version
        if not force:
            cached = self.cache.get(db, TASK, job_hash, profile.version, version)
            if cached is not None:
                log_event("AI_CACHE_HIT", task=TASK, job_id=job.id)
                resume, _ = ground_resume(TailoredResume.model_validate(cached.result), profile)
                return resume, f"{cached.provider}:{cached.model}"
        prompt = render_prompt(load_prompt("resume_tailoring", version), profile_json=profile_to_json(profile), job=job_to_prompt_text(job, 5000))
        try:
            resume, meta = await self.ai.complete_json(TASK, prompt, TailoredResume, system=SYSTEM_PROMPT, temperature=0.3, max_tokens=3000)
        except AIUnavailableError as e:
            raise TailoringFailed(str(e)) from e
        resume, removed = ground_resume(resume, profile)
        if removed:
            log_event("RESUME_GROUNDING", job_id=job.id, removed=removed[:10])
        self.cache.put(
            db, task=TASK, job_hash=job_hash, profile_version=profile.version, prompt_version=version,
            model=meta.model, provider=meta.provider, result=resume.model_dump(mode="json"), usage=meta.usage,
        )
        db.commit()
        return resume, f"{meta.provider}:{meta.model}"

    async def tailor_for_job(self, db: Session, job: Job, force: bool = False) -> tuple[Application, TailoredResume]:
        """Create (or reuse) the application for this job and attach a tailored resume + PDF."""
        profile = get_profile(db)
        app = application_service.get_application_for_job(db, job.id)
        if app is None:
            app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.APPROVED))
        resume, model = await self.generate(db, job, profile, force=force)
        self.attach(db, app, resume, profile, model)
        return app, resume

    def attach(self, db: Session, app: Application, resume: TailoredResume, profile: Profile, model: str) -> None:
        version_n = int((app.resume_version or "v0").rsplit("v", 1)[-1] or 0) + 1
        path = render_resume_pdf(resume, profile, resume_path_for(app.id, version_n))
        app.tailored_resume = resume.model_dump(mode="json")
        app.resume_version = f"tailored-v{version_n}"
        app.resume_path = str(path)
        app.prepared_at = datetime.now(timezone.utc)
        if app.match_score is None and app.job is not None:
            app.match_score = app.job.match_score
        db.add(app)
        db.commit()
        db.refresh(app)
        log_event("RESUME_TAILORED", application_id=app.id, job_id=app.job_id, version=app.resume_version, model=model)
