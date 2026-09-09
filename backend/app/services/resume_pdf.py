"""Render a TailoredResume to a simple, clean PDF with fpdf2 (core fonts, no downloads)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from ..config import DATA_DIR
from ..models import Profile
from ..schemas.ai import TailoredResume

RESUME_DIR = DATA_DIR / "resumes"

_REPLACEMENTS = {
    "•": "-", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", " ": " ", "→": "->", "✓": "+", "✔": "+",
}


def latin(text: str) -> str:
    """Core PDF fonts only support Latin-1; replace common typographic characters first."""
    for k, v in _REPLACEMENTS.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


class _ResumePDF(FPDF):
    def section(self, title: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(30, 30, 30)
        self.cell(0, 6, latin(title.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(120, 120, 120)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(0, 0, 0)

    def para(self, text: str, size: float = 10, style: str = "") -> None:
        self.set_font("Helvetica", style, size)
        self.multi_cell(0, 4.8, latin(text), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.cell(4, 4.8, "-")
        self.multi_cell(0, 4.8, latin(text), new_x="LMARGIN", new_y="NEXT")


def render_resume_pdf(resume: TailoredResume, profile: Profile, path: Path) -> Path:
    pdf = _ResumePDF(format="A4")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 8, latin(profile.full_name), new_x="LMARGIN", new_y="NEXT")
    if resume.headline:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 6, latin(resume.headline), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    contact = " | ".join(
        c for c in [profile.email, profile.phone, profile.current_location, profile.linkedin_url, profile.github_url, profile.portfolio_url] if c
    )
    if contact:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 4.5, latin(contact), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    if resume.summary:
        pdf.section("Summary")
        pdf.para(resume.summary)
    if resume.skills:
        pdf.section("Skills")
        pdf.para(", ".join(resume.skills))
    if resume.experience:
        pdf.section("Experience")
        for exp in resume.experience:
            pdf.set_font("Helvetica", "B", 10.5)
            dates = f"{exp.start} - {exp.end}".strip(" -") if (exp.start or exp.end) else ""
            pdf.cell(0, 5.5, latin(f"{exp.title} - {exp.company}"), new_x="LMARGIN", new_y="NEXT")
            if dates:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(90, 90, 90)
                pdf.cell(0, 4.5, latin(dates), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            for b in exp.bullets:
                pdf.bullet(b)
            pdf.ln(1)
    if resume.projects:
        pdf.section("Projects")
        for proj in resume.projects:
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.cell(0, 5.5, latin(proj.name), new_x="LMARGIN", new_y="NEXT")
            if proj.description:
                pdf.para(proj.description)
            if proj.technologies:
                pdf.para("Technologies: " + ", ".join(proj.technologies), size=9, style="I")
            pdf.ln(1)
    if resume.education:
        pdf.section("Education")
        for e in resume.education:
            pdf.bullet(e)
    if resume.certifications:
        pdf.section("Certifications")
        for c in resume.certifications:
            pdf.bullet(c)
    if resume.achievements:
        pdf.section("Achievements")
        for a in resume.achievements:
            pdf.bullet(a)

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def resume_path_for(application_id: int, version: int) -> Path:
    return RESUME_DIR / f"application_{application_id}_v{version}.pdf"
