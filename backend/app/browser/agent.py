"""Playwright browser agent (spec section 10) with an optional, heavily guarded auto-submit.

    open URL -> (follow the "Apply" link if the page is only a job description)
    -> inspect page -> identify form fields -> map to profile -> fill safe fields
    -> upload resume -> answer text questions -> STOP before submission

Manual mode (default): the browser window stays open so the user reviews and submits.
Auto mode (`submit=True`): the form is submitted ONLY when every guard passes -
no CAPTCHA on the page, a real submit button, every required field filled, no
answer flagged for review.  CAPTCHAs and logins are never bypassed.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from .field_mapper import FillAction, FormField, looks_like_question, map_fields, match_existing_answer, submit_blockers

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
      options: opts, required: !!el.required || el.getAttribute('aria-required') === 'true', value: String(el.value || '').slice(0, 100),
      accept: el.getAttribute('accept') || '', maxlength: el.maxLength > 0 ? el.maxLength : null,
    });
    idx++;
  }
  const submitEls = Array.from(document.querySelectorAll('button, input[type="submit"]'))
    .filter(b => visible(b) && /submit|apply|send|finish|complete application/i.test((b.innerText || b.value || '')) && !/apply with|autofill|linkedin|indeed/i.test((b.innerText || b.value || '')));
  submitEls.forEach((b, i) => b.setAttribute('data-jobagent-submit', String(i)));
  const submits = submitEls.map(b => (b.innerText || b.value || '').trim()).slice(0, 5);
  const captcha = !!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], #captcha, [name*="captcha" i]');
  const applyCandidates = Array.from(document.querySelectorAll('a, button'))
    .filter(a => visible(a))
    .map(a => ({ text: (a.innerText || a.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim(), href: a.getAttribute('href') || '' }))
    .filter(c => c.text.length < 60 && /\\bapply\\b|i'm interested|easy apply/i.test(c.text) && !/apply with|autofill|filter|search/i.test(c.text))
    .filter(c => c.href && !c.href.startsWith('javascript') && !c.href.startsWith('mailto'));
  // external / absolute application links first (job boards usually hand off to the employer's ATS)
  applyCandidates.sort((a, b) => (b.href.startsWith('http') ? 1 : 0) - (a.href.startsWith('http') ? 1 : 0));
  const applyLinks = applyCandidates.map(c => c.href);
  return { fields, submits, captcha, title: document.title, applyLinks: applyLinks.slice(0, 3), bodyText: (document.body ? document.body.innerText : '').slice(0, 4000) };
}
"""

SUCCESS_PATTERNS = re.compile(
    r"thank you for (applying|your application|submitting)|application (has been |was )?(received|submitted|sent|complete)|"
    r"successfully (applied|submitted)|we('ve| have) received your application|your application is (in|complete)|"
    r"application submitted|you have applied|thanks for applying",
    re.IGNORECASE,
)


@dataclass
class BrowserSession:
    application_id: int
    playwright: Any
    browser: Any
    context: Any
    page: Any
    frames: list[Any] = field(default_factory=list)


@dataclass
class ScanResult:
    fields: list[FormField]
    submits: list[str]
    captcha: bool
    title: str
    apply_links: list[str]
    body_text: str


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

    async def _launch_persistent(self, application_id: int) -> BrowserSession:
        """Headed browser with a persistent profile (data/browser_profile) so the user's own
        logins to LinkedIn / Naukri / Indeed survive between assisted sessions."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium") from e
        from ..config import DATA_DIR

        profile_dir = DATA_DIR / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        pw = await async_playwright().start()
        try:
            context = await pw.chromium.launch_persistent_context(
                str(profile_dir), headless=False, viewport={"width": 1280, "height": 900}, accept_downloads=False,
                slow_mo=self.settings.browser_slow_mo_ms or 0,
            )
        except Exception as e:  # noqa: BLE001
            await pw.stop()
            raise RuntimeError(f"Could not launch Chromium with the persistent profile: {e}") from e
        context.set_default_timeout(self.settings.browser_timeout_ms)
        page = context.pages[0] if context.pages else await context.new_page()
        session = BrowserSession(application_id, pw, context.browser or context, context, page)
        self.sessions[application_id] = session
        return session

    async def assist_application(self, db: Session, app: Application, url: str | None = None) -> FillResponse:
        """Assisted mode for sites that forbid automation: open the posting in the user's own
        logged-in browser, reveal the application form, pre-fill it - and stop.  The user submits."""
        target = self._validate_url(url or app.job_url)
        profile = get_profile(db)
        resume_path = app.resume_path if app.resume_path and Path(app.resume_path).exists() else None
        job_remote = app.job.remote_type.value if app.job is not None and app.job.remote_type else None
        log_event("APPLICATION_STARTED", application_id=app.id, url=target, stage="browser_assist")
        async with self._lock:
            await self.close_session(app.id)
            try:
                session = await self._launch_persistent(app.id)
            except RuntimeError as e:
                app.last_error = str(e)[:1000]
                db.commit()
                return FillResponse(ok=False, message=str(e))
            page = session.page
            try:
                await page.goto(target, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                scan = await self._scan_or_follow_apply(session, max_hops=1)
                login_wall = bool(re.search(r"sign in|log in|join now|create account", scan.body_text[:3000], re.I)) and len(scan.fields) < 3
                actions, question_fields, unmatched = map_fields(scan.fields, profile, resume_path, app.cover_note or "", job_remote)
                answer_actions, unanswered = await self._plan_answers(db, app, question_fields)
                actions.extend(answer_actions)
                unmatched.extend(unanswered)
                filled = await self._apply(session, actions)
                blockers = submit_blockers(actions, unmatched, scan.submits, scan.captcha, len(scan.fields))
                result = self._build_result(actions, unmatched, scan, filled, resume_path, keep_open=True, submitted=False, evidence="", blockers=blockers, final_url=page.url)
                if login_wall:
                    result.message = "This site wants you to log in first. Log in inside the opened browser window (your login is remembered), then click 'Assist in browser' again. " + result.message
            except Exception as e:  # noqa: BLE001
                app.last_error = f"Assisted browser session failed: {type(e).__name__}: {e}"[:1000]
                db.commit()
                await self.close_session(app.id)
                return FillResponse(ok=False, message=app.last_error)
        app.fill_result = {**result.model_dump(), "at": datetime.now(timezone.utc).isoformat(), "mode": "assist"}
        app.last_error = ""
        if app.status in (ApplicationStatus.APPROVED, ApplicationStatus.PREPARING):
            application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="assisted fill, awaiting your submit")
        db.commit()
        log_event("APPLICATION_FILLED", application_id=app.id, mode="assist", fields_filled=result.fields_filled, unmatched=len(result.unmatched_fields))
        return result

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

    async def fill_application(
        self, db: Session, app: Application, url: str | None = None, headless: bool | None = None, submit: bool = False
    ) -> FillResponse:
        target = self._validate_url(url or app.job_url)
        headless = self.settings.browser_headless if headless is None else headless
        profile = get_profile(db)
        resume_path = app.resume_path if app.resume_path and Path(app.resume_path).exists() else None
        job_remote = app.job.remote_type.value if app.job is not None and app.job.remote_type else None
        log_event("APPLICATION_STARTED", application_id=app.id, url=target, stage="browser_fill", auto_submit=submit)

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
                scan = await self._scan_or_follow_apply(session)
                actions, question_fields, unmatched = map_fields(scan.fields, profile, resume_path, app.cover_note or "", job_remote)
                answer_actions, unanswered = await self._plan_answers(db, app, question_fields)
                actions.extend(answer_actions)
                unmatched.extend(unanswered)
                filled = await self._apply(session, actions)
                blockers = submit_blockers(actions, unmatched, scan.submits, scan.captcha, len(scan.fields))
                submitted = False
                evidence = ""
                if submit and not blockers:
                    submitted, evidence = await self._submit(session)
                    if not submitted:
                        blockers.append(f"submission not confirmed: {evidence or 'no success message detected'}")
                elif not submit:
                    submitted = await self._detect_marker(page)
                result = self._build_result(
                    actions, unmatched, scan, filled, resume_path,
                    keep_open=(self.settings.browser_keep_open and not headless and not submit),
                    submitted=submitted, evidence=evidence, blockers=blockers, final_url=page.url,
                )
            except Exception as e:  # noqa: BLE001
                app.last_error = f"Browser fill failed: {type(e).__name__}: {e}"[:1000]
                db.commit()
                log_event("APPLICATION_FAILED", application_id=app.id, error=str(e)[:300], level=logging.ERROR)
                await self.close_session(app.id)
                return FillResponse(ok=False, message=app.last_error)

            if not result.browser_open:
                await self.close_session(app.id)

        app.fill_result = {**result.model_dump(), "at": datetime.now(timezone.utc).isoformat(), "auto_submit": submit}
        app.last_error = ""
        if result.submitted and submit:
            if app.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED):
                application_service.transition_status(db, app, ApplicationStatus.APPROVED, note="auto-apply")
            if app.status in (ApplicationStatus.APPROVED, ApplicationStatus.PREPARING):
                application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="form filled by the browser agent")
            if app.status != ApplicationStatus.APPLIED:
                application_service.transition_status(db, app, ApplicationStatus.APPLIED, note="auto-submitted by the browser agent")
        elif app.status in (ApplicationStatus.APPROVED, ApplicationStatus.PREPARING):
            application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="form filled, awaiting manual submit")
        db.commit()
        log_event(
            "APPLICATION_SUBMITTED" if (result.submitted and submit) else "APPLICATION_FILLED",
            application_id=app.id, fields_filled=result.fields_filled, questions_answered=result.questions_answered,
            resume_uploaded=result.resume_uploaded, unmatched=len(result.unmatched_fields), blockers=result.blockers[:5],
        )
        return result

    # ---------------------------------------------------------------- scan
    async def _scan(self, session: BrowserSession) -> ScanResult:
        fields: list[FormField] = []
        submits: list[str] = []
        apply_links: list[str] = []
        captcha = False
        title = ""
        body_text = ""
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
            captcha = captcha or bool(data.get("captcha"))
            if idx == 0:
                title = data.get("title", "")
                body_text = data.get("bodyText", "") or ""
                apply_links = data.get("applyLinks", []) or []
        return ScanResult(fields, submits, captcha, title, apply_links, body_text)

    async def _scan_or_follow_apply(self, session: BrowserSession, max_hops: int = 2) -> ScanResult:
        """Job-board pages often show the description with an 'Apply' link to the real form."""
        scan = await self._scan(session)
        hops = 0
        while len(scan.fields) < 3 and scan.apply_links and hops < max_hops:
            href = scan.apply_links[0]
            try:
                if href.startswith("#"):
                    await session.page.click(f"a[href='{href}']", timeout=5000)
                else:
                    await session.page.goto(href if href.startswith("http") else session.page.url.rsplit("/", 1)[0] + "/" + href.lstrip("/"), wait_until="domcontentloaded")
                await session.page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                break
            hops += 1
            scan = await self._scan(session)
        return scan

    # ------------------------------------------------------------- answers
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

    # --------------------------------------------------------------- apply
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

    # -------------------------------------------------------------- submit
    async def _submit(self, session: BrowserSession) -> tuple[bool, str]:
        """Click the submit button and look for evidence of success.  Only called when no blockers exist."""
        page = session.page
        before_url = page.url
        clicked = False
        for frame in session.frames or [page]:
            try:
                btn = frame.locator("[data-jobagent-submit='0']").first
                if await btn.count() > 0:
                    await btn.click(timeout=10000)
                    clicked = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            return False, "could not click the submit button"
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # noqa: BLE001 - some pages never go idle
            pass
        await page.wait_for_timeout(1500)
        if await self._detect_marker(page):
            return True, "page marked the application as submitted"
        try:
            body = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 6000) : ''")
        except Exception:  # noqa: BLE001
            body = ""
        m = SUCCESS_PATTERNS.search(body or "")
        if m:
            return True, f"success message: '{m.group(0)}'"
        try:
            remaining = await page.evaluate("() => document.querySelectorAll('[data-jobagent-idx]').length")
        except Exception:  # noqa: BLE001
            remaining = -1
        if page.url != before_url and remaining == 0:
            return True, f"form disappeared after navigation to {page.url}"
        try:
            errors = await page.evaluate(
                "() => Array.from(document.querySelectorAll('[aria-invalid=\"true\"], .error, .field-error, [role=alert]')).map(e => (e.innerText||'').trim()).filter(Boolean).slice(0,3)"
            )
        except Exception:  # noqa: BLE001
            errors = []
        if errors:
            return False, "form reported errors: " + "; ".join(str(e)[:80] for e in errors)
        return False, "no confirmation message after clicking submit"

    @staticmethod
    async def _detect_marker(page: Any) -> bool:
        try:
            marker = page.locator("[data-submitted='1']")
            return await marker.count() > 0
        except Exception:  # noqa: BLE001
            return False

    # -------------------------------------------------------------- result
    @staticmethod
    def _build_result(
        actions: list[FillAction], unmatched: list[FormField], scan: ScanResult, filled: int, resume_path: str | None,
        keep_open: bool, submitted: bool, evidence: str, blockers: list[str], final_url: str,
    ) -> FillResponse:
        questions_answered = sum(1 for a in actions if a.source == "answer" and a.status == "filled")
        resume_uploaded = any(a.action == "upload" and a.status == "uploaded" for a in actions)
        failed = [a for a in actions if a.status == "failed"]
        msg = f"Filled {filled} field(s) on '{scan.title or 'page'}'."
        if failed:
            msg += f" {len(failed)} field(s) could not be filled."
        if unmatched:
            msg += f" {len(unmatched)} field(s) need your input."
        if submitted and evidence:
            msg += f" SUBMITTED ({evidence})."
        elif blockers:
            msg += " Not submitted: " + "; ".join(blockers[:3]) + "."
        else:
            msg += " The form was NOT submitted"
            msg += f" - submit button(s) found: {', '.join(scan.submits)}." if scan.submits else "."
        return FillResponse(
            ok=True, message=msg, fields_filled=filled, questions_answered=questions_answered,
            resume_uploaded=resume_uploaded, fields=[a.to_dict() for a in actions],
            unmatched_fields=[{"label": f.display, "selector": f.selector, "kind": f.kind, "name": f.name, "required": f.required} for f in unmatched],
            browser_open=keep_open, resume=Path(resume_path).name if resume_path else "",
            submitted=submitted, submit_evidence=evidence, blockers=blockers, final_url=final_url, captcha_detected=scan.captcha,
        )
