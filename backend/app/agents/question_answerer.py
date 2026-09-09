"""Grounded answers to application-form questions (spec section 9)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai.base import AIUnavailableError
from ..ai.cache import AIResultCache, job_hash_for, text_hash
from ..ai.prompts import load_prompt, render_prompt
from ..ai.router import AIRouter
from ..config import Settings
from ..logging_config import log_event
from ..models import Job, Profile
from ..schemas.ai import QuestionAnswer, QuestionAnswerBatch
from ..services.profile_service import get_profile, profile_to_prompt_text
from .job_analyzer import SYSTEM_PROMPT, job_to_prompt_text

TASK = "application_questions"

DEFAULT_QUESTIONS = [
    "Why do you want this role?",
    "Why do you want to work at this company?",
    "Tell us about yourself.",
    "Describe your most relevant experience for this role.",
    "Describe your AI/ML experience.",
    "Describe your backend engineering experience.",
    "What are your salary expectations?",
    "What is your notice period?",
    "Are you willing to relocate?",
    "What is your work authorization status?",
]

_SENSITIVE_HINTS = ("salary", "compensation", "ctc", "notice period", "relocat", "authoriz", "visa", "sponsorship", "citizenship")


class AnsweringFailed(Exception):
    pass


def _postprocess(batch: QuestionAnswerBatch, questions: list[str], profile: Profile) -> list[QuestionAnswer]:
    """Guarantee one answer per question and flag anything the profile cannot support."""
    by_q = {a.question.strip().lower(): a for a in batch.answers}
    out: list[QuestionAnswer] = []
    for i, q in enumerate(questions):
        ans = by_q.get(q.strip().lower())
        if ans is None and i < len(batch.answers):
            ans = batch.answers[i]
        if ans is None:
            ans = QuestionAnswer(question=q, answer="", confidence=0.0, needs_review=True)
        ans.question = q
        if not ans.answer.strip():
            ans.needs_review = True
            ans.confidence = min(ans.confidence, 0.3)
        ql = q.lower()
        if "salary" in ql or "compensation" in ql or "ctc" in ql:
            if not (profile.expected_salary or "").strip():
                ans.needs_review = True
        if "notice" in ql and not (profile.notice_period or "").strip():
            ans.needs_review = True
        if ("authoriz" in ql or "visa" in ql or "sponsor" in ql or "citizen" in ql) and not (profile.work_authorization or "").strip():
            ans.needs_review = True
        if ans.confidence < 0.5:
            ans.needs_review = True
        out.append(ans)
    return out


class QuestionAnswerer:
    def __init__(self, ai_router: AIRouter, settings: Settings, cache: AIResultCache | None = None):
        self.ai = ai_router
        self.settings = settings
        self.cache = cache or AIResultCache()

    async def answer(self, db: Session, job: Job, questions: list[str], profile: Profile | None = None, force: bool = False) -> list[QuestionAnswer]:
        questions = [q.strip() for q in questions if q and q.strip()]
        if not questions:
            return []
        profile = profile or get_profile(db)
        version = self.settings.application_questions_prompt_version
        key = text_hash(job_hash_for(job), "\n".join(questions))
        if not force:
            cached = self.cache.get(db, TASK, key, profile.version, version)
            if cached is not None:
                log_event("AI_CACHE_HIT", task=TASK, job_id=job.id)
                return _postprocess(QuestionAnswerBatch.model_validate(cached.result), questions, profile)
        prompt = render_prompt(
            load_prompt("application_questions", version),
            profile=profile_to_prompt_text(profile, include_contact=False),
            job=job_to_prompt_text(job, 4000),
            questions="\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)),
        )
        try:
            batch, meta = await self.ai.complete_json(TASK, prompt, QuestionAnswerBatch, system=SYSTEM_PROMPT, temperature=0.4, max_tokens=3000)
        except AIUnavailableError as e:
            raise AnsweringFailed(str(e)) from e
        answers = _postprocess(batch, questions, profile)
        self.cache.put(
            db, task=TASK, job_hash=key, profile_version=profile.version, prompt_version=version,
            model=meta.model, provider=meta.provider, result={"answers": [a.model_dump() for a in answers]}, usage=meta.usage,
        )
        db.commit()
        log_event("QUESTIONS_ANSWERED", job_id=job.id, count=len(answers), needs_review=sum(a.needs_review for a in answers))
        return answers
