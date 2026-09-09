"""Playwright browser agent (spec section 10).

    open URL -> inspect page -> identify form fields -> map to profile -> fill safe fields
    -> upload resume -> answer text questions -> STOP before submission

The browser window stays open (when not headless) so the user can review and press
submit themselves.  The agent never clicks submit buttons, never bypasses CAPTCHAs
or logins, and only runs our own small DOM-inspection script.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..agents.question_answerer import AnsweringFailed, QuestionAnswerer
from ..config import Settings
from ..logging_config import log_event
from ..models import Application, ApplicationStatus
from ..schemas.application import FillResponse
from ..services import application_service
from ..services.profile_service import get_profile
from .field_mapper import FillAction, FormField, looks_like_question, map_fields, match_existing_answer

SCAN_SCRIPT = """
() => {
  const fields = [];
  const els = document.querySelectorAll('input, textarea, select');
  let idx = 0;
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const textOf = (n) => (n && (n.innerText || n.textContent) || '').replace(/\\s+/g, ' ').trim();
  for (const el of els) {
    const type = (el.getAttribute('type') || (el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select' : 'text')).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type)) continue;
    if (type !== 'file' && !visible(el)) continue;
    let label = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = textOf(l); }
    if (!label) { const p = el.closest('label'); if (p) label = textOf(p); }
    if (!label && el.getAttribute('aria-labelledby')) {
      label = el.getAttribute('aria-labelledby').split(/\\s+/).map(id => textOf(document.getElementById(id))).join(' ');
    }
    if (!label) {
      let prev = el.previousElementSibling;
      if (prev && ['LABEL', 'SPAN', 'DIV', 'P', 'LEGEND', 'H1', 'H2', 'H3', 'H4', 'STRONG', 'B'].includes(prev.tagName)) label = textOf(prev);
    }
    if (!label) {
      const wrapper = el.closest('div, fieldset, li');
      if (wrapper) { const l = wrapper.querySelector('label, legend'); if (l) label = textOf(l); }
    }
    const opts = el.tagName === 'SELECT' ? Array.from(el.options).map(o => (o.text || '').trim()) : [];
    el.setAttribute('data-jobagent-idx', String(idx));
    fields.push({
      selector: '[data-jobagent-idx="' + idx + '"]', kind: type, label: (label || '').slice(0, 200),
      name: el.getAttribute('name') || '', id: el.id || '', placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '', autocomplete: el.getAttribute('autocomplete') || '',
      options: opts, required: !!el.required, value: String(el.value || '').slice(0, 100),
      accept: el.getAttribute('accept') || '', maxlength: el.maxLength > 0 ? el.maxLength : null,
    });
    idx++;
  }
  const submits = Array.from(document.querySelectorAll('button, input[type="submit"]'))
    .filter(b => /submit|apply|send|finish/i.test((b.innerText || b.value || '')))
    .map(b => (b.innerText || b.value || '').trim()).slice(0, 5);
  return { fields, submits, title: document.title };
}
"""


@dataclass
class BrowserSession:
    application_id: int
    playwright: Any
    browser: Any
    context: Any
    page: Any
    frames: list[Any] = field(default_factory=list)


class BrowserAgent:
    def __init__(self, settings: Settings, answerer: QuestionAnswerer | None = None):
        self.settings = settings
        self.answerer = answerer
        self.sessions: dict[int, BrowserSession] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ sessions
    async def _launch(self, application_id: int, headless: bool) -> BrowserSession:
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium") from e
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(headless=headless, slow_mo=self.settings.browser_slow_mo_ms or 0)
        except Exception as e:  # noqa: BLE001
            await pw.stop()
            raise RuntimeError(f"Could not launch Chromium: {e}. Run: python -m playwright install chromium") from e
        context = await browser.new_context(accept_downloads=False, viewport={"width": 1280, "height": 900})
        context.set_default_timeout(self.settings.browser_timeout_ms)
        page = await context.new_page()
        session = BrowserSession(application_id, pw, browser, context, page)
        self.sessions[application_id] = session
        return session

    async def close_session(self, application_id: int) -> bool:
        session = self.sessions.pop(application_id, None)
        if session is None:
            return False
        for closer in (session.context.close, session.browser.close, session.playwright.stop):
            try:
                await closer()
            except Exception:  # noqa: BLE001
                pass
        return True

    async def shutdown(self) -> None:
        for app_id in list(self.sessions):
            await self.close_session(app_id)

    # ---------------------------------------------------------------- fill
    @staticmethod
    def _validate_url(url: str) -> str:
        parsed = urlparse(url or "")
        if parsed.scheme not in ("http", "https", "file"):
            raise ValueError("Application URL must start with http://, https:// or file://")
        return url

    async def fill_application(self, db: Session, app: Application, url: str | None = None, headless: bool | None = None) -> FillResponse:
        target = self._validate_url(url or app.job_url)
        headless = self.settings.browser_headless if headless is None else headless
        profile = get_profile(db)
        resume_path = app.resume_path if app.resume_path and Path(app.resume_path).exists() else None
        log_event("APPLICATION_STARTED", application_id=app.id, url=target, stage="browser_fill")

        async with self._lock:
            await self.close_session(app.id)
            try:
                session = await self._launch(app.id, headless)
            except RuntimeError as e:
                app.last_error = str(e)[:1000]
                db.commit()
                log_event("APPLICATION_FAILED", application_id=app.id, error=str(e)[:300], level=logging.ERROR)
                return FillResponse(ok=False, message=str(e))
            page = session.page
            try:
                await page.goto(target, wait_until="domcontentloaded")
                await page.wait_for_timeout(800)  # let client-side forms render
                fields, submits, title = await self._scan(session)
                actions, question_fields, unmatched = map_fields(fields, profile, resume_path, app.cover_note or "")
                answer_actions, unanswered = await self._plan_answers(db, app, question_fields)
                actions.extend(answer_actions)
                unmatched.extend(unanswered)
                filled = await self._apply(session, actions)
                submitted = await self._detect_submission(page)
                result = self._build_result(app, actions, unmatched, submits, title, filled, resume_path, keep_open=(self.settings.browser_keep_open and not headless), submitted=submitted)
            except Exception as e:  # noqa: BLE001
                app.last_error = f"Browser fill failed: {type(e).__name__}: {e}"[:1000]
                db.commit()
                log_event("APPLICATION_FAILED", application_id=app.id, error=str(e)[:300], level=logging.ERROR)
                await self.close_session(app.id)
                return FillResponse(ok=False, message=app.last_error)

            if not (self.settings.browser_keep_open and not headless):
                await self.close_session(app.id)

        app.fill_result = result.model_dump()
        app.last_error = ""
        if app.status in (ApplicationStatus.APPROVED, ApplicationStatus.PREPARING):
            application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="form filled, awaiting manual submit")
        db.commit()
        log_event(
            "APPLICATION_FILLED", application_id=app.id, fields_filled=result.fields_filled,
            questions_answered=result.questions_answered, resume_uploaded=result.resume_uploaded, unmatched=len(result.unmatched_fields),
        )
        return result

    async def _scan(self, session: BrowserSession) -> tuple[list[FormField], list[str], str]:
        fields: list[FormField] = []
        submits: list[str] = []
        title = ""
        session.frames = []
        for idx, frame in enumerate(session.page.frames):
            try:
                data = await frame.evaluate(SCAN_SCRIPT)
            except Exception:  # noqa: BLE001 - cross-origin or detached frames
                continue
            session.frames.append(frame)
            frame_index = len(session.frames) - 1
            for d in data.get("fields", []):
                fields.append(FormField.from_dict(d, frame=frame_index))
            submits.extend(data.get("submits", []))
            if idx == 0:
                title = data.get("title", "")
        return fields, submits, title

    async def _plan_answers(self, db: Session, app: Application, question_fields: list[FormField]) -> tuple[list[FillAction], list[FormField]]:
        actions: list[FillAction] = []
        unanswered: list[FormField] = []
        existing = [a for a in (app.answers or []) if isinstance(a, dict)]
        need_ai: list[FormField] = []
        for f in question_fields:
            question = (f.label or f.placeholder or f.aria_label or f.name).strip()
            hit = match_existing_answer(question, existing)
            if hit and not hit.get("needs_review"):
                actions.append(FillAction(f, "fill", str(hit["answer"]), "answer", note="from prepared answers"))
            elif looks_like_question(f) or f.kind == "textarea":
                need_ai.append(f)
            else:
                unanswered.append(f)
        if need_ai and self.answerer is not None and app.job is not None and self.answerer.ai.is_available():
            questions = [(f.label or f.placeholder or f.aria_label or f.name).strip() for f in need_ai]
            try:
                answers = await self.answerer.answer(db, app.job, questions)
                by_q = {a.question: a for a in answers}
                new_records = []
                for f, q in zip(need_ai, questions):
                    a = by_q.get(q)
                    if a is None:
                        unanswered.append(f)
                        continue
                    new_records.append(a.model_dump())
                    if a.answer.strip() and not a.needs_review:
                        actions.append(FillAction(f, "fill", a.answer, "answer", note="generated"))
                    else:
                        unanswered.append(f)
                app.answers = [*existing, *new_records]
                db.commit()
            except AnsweringFailed:
                unanswered.extend(need_ai)
        else:
            unanswered.extend(need_ai)
        return actions, unanswered

    async def _apply(self, session: BrowserSession, actions: list[FillAction]) -> int:
        filled = 0
        for act in actions:
            if act.status == "skipped":
                continue
            frame = session.frames[act.field.frame] if act.field.frame < len(session.frames) else session.page
            locator = frame.locator(act.field.selector).first
            try:
                if act.action == "upload":
                    await locator.set_input_files(act.value)
                    act.status = "uploaded"
                elif act.action == "select":
                    await locator.select_option(label=act.value)
                    act.status = "filled"
                elif act.action == "check":
                    await locator.check()
                    act.status = "filled"
                else:
                    await locator.fill(act.value)
                    act.status = "filled"
                filled += 1
            except Exception as e:  # noqa: BLE001 - one bad field must not stop the rest
                act.status = "failed"
                act.note = f"{type(e).__name__}: {str(e)[:120]}"
        return filled

    @staticmethod
    async def _detect_submission(page: Any) -> bool:
        try:
            marker = page.locator("[data-submitted='1']")
            return await marker.count() > 0
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _build_result(
        app: Application, actions: list[FillAction], unmatched: list[FormField], submits: list[str], title: str,
        filled: int, resume_path: str | None, keep_open: bool, submitted: bool,
    ) -> FillResponse:
        questions_answered = sum(1 for a in actions if a.source == "answer" and a.status == "filled")
        resume_uploaded = any(a.action == "upload" and a.status == "uploaded" for a in actions)
        failed = [a for a in actions if a.status == "failed"]
        msg = f"Filled {filled} field(s) on '{title or 'page'}'."
        if failed:
            msg += f" {len(failed)} field(s) could not be filled."
        if unmatched:
            msg += f" {len(unmatched)} field(s) need your input."
        msg += " The form was NOT submitted"
        msg += f" - submit button(s) found: {', '.join(submits)}." if submits else "."
        if submitted:
            msg += " WARNING: the page reports a submission; please verify."
        return FillResponse(
            ok=True, message=msg, fields_filled=filled, questions_answered=questions_answered,
            resume_uploaded=resume_uploaded, fields=[a.to_dict() for a in actions],
            unmatched_fields=[{"label": f.label or f.placeholder or f.aria_label, "selector": f.selector, "kind": f.kind, "name": f.name} for f in unmatched],
            browser_open=keep_open, resume=Path(resume_path).name if resume_path else "",
        )
