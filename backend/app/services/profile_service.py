"""Profile read / update helpers and the profile -> prompt text renderer."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Profile
from ..schemas.profile import ProfileUpdate


def get_profile(db: Session) -> Profile:
    profile = db.execute(select(Profile).order_by(Profile.id)).scalars().first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found. Seed the database first.")
    return profile


def get_profile_or_none(db: Session) -> Profile | None:
    return db.execute(select(Profile).order_by(Profile.id)).scalars().first()


def update_profile(db: Session, data: ProfileUpdate) -> Profile:
    profile = get_profile(db)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return profile
    for key, value in changes.items():
        if isinstance(value, list):
            value = [v.model_dump() if hasattr(v, "model_dump") else v for v in value]
        setattr(profile, key, value)
    profile.version = (profile.version or 1) + 1
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def profile_to_prompt_text(profile: Profile, include_contact: bool = False) -> str:
    """Render the profile as compact structured text for LLM prompts.

    Contact details are excluded by default (not needed for matching, keeps prompts small).
    """
    lines: list[str] = []
    lines.append(f"Name: {profile.full_name}")
    if include_contact:
        lines.append(f"Email: {profile.email} | Phone: {profile.phone}")
        if profile.linkedin_url:
            lines.append(f"LinkedIn: {profile.linkedin_url}")
        if profile.github_url:
            lines.append(f"GitHub: {profile.github_url}")
        if profile.portfolio_url:
            lines.append(f"Portfolio: {profile.portfolio_url}")
    lines.append(f"Current location: {profile.current_location}")
    lines.append(f"Preferred locations: {', '.join(profile.preferred_locations or [])}")
    lines.append(f"Remote preference: {profile.remote_preference}")
    lines.append(f"Years of experience: {profile.years_of_experience}")
    lines.append(f"Current role: {profile.current_role} at {profile.current_company}")
    lines.append(f"Notice period: {profile.notice_period or 'not specified'}")
    lines.append(f"Expected salary: {profile.expected_salary or 'not specified'}")
    lines.append(f"Work authorization: {profile.work_authorization or 'not specified'}")
    if profile.summary:
        lines.append(f"Summary: {profile.summary}")
    lines.append(f"Skills: {', '.join(profile.skills or [])}")
    if profile.technologies:
        lines.append(f"Technologies: {', '.join(profile.technologies)}")
    lines.append("")
    lines.append("Experience:")
    for exp in profile.experience or []:
        lines.append(f"- {exp.get('title')} at {exp.get('company')} ({exp.get('start', '')} - {exp.get('end', '') or 'Present'})")
        for b in exp.get("bullets", []) or []:
            lines.append(f"    * {b}")
        if exp.get("technologies"):
            lines.append(f"    Technologies: {', '.join(exp['technologies'])}")
    lines.append("")
    lines.append("Projects:")
    for proj in profile.projects or []:
        lines.append(f"- {proj.get('name')}: {proj.get('description', '')}")
        if proj.get("technologies"):
            lines.append(f"    Technologies: {', '.join(proj['technologies'])}")
        for b in proj.get("bullets", []) or []:
            lines.append(f"    * {b}")
    lines.append("")
    lines.append("Education:")
    for edu in profile.education or []:
        lines.append(f"- {edu.get('degree')} - {edu.get('institution', '')} ({edu.get('year', '')})")
    if profile.certifications:
        lines.append("Certifications: " + "; ".join(profile.certifications))
    if profile.achievements:
        lines.append("Achievements:")
        for a in profile.achievements:
            lines.append(f"- {a}")
    lines.append("")
    lines.append("Job preferences:")
    lines.append(f"- Target roles: {', '.join(profile.target_roles or [])}")
    lines.append(f"- Target locations: {', '.join(profile.target_locations or [])}")
    lines.append(f"- Experience range: {profile.experience_min}-{profile.experience_max} years")
    if profile.minimum_salary:
        lines.append(f"- Minimum salary: {profile.minimum_salary} {profile.salary_currency}")
    if profile.preferred_industries:
        lines.append(f"- Preferred industries: {', '.join(profile.preferred_industries)}")
    if profile.keywords_prioritize:
        lines.append(f"- Keywords to prioritize: {', '.join(profile.keywords_prioritize)}")
    if profile.keywords_reject:
        lines.append(f"- Keywords to reject: {', '.join(profile.keywords_reject)}")
    return "\n".join(lines)


def profile_to_json(profile: Profile) -> str:
    """Full profile as JSON (used for resume tailoring / question answering)."""
    data = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "current_location": profile.current_location,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
        "years_of_experience": profile.years_of_experience,
        "notice_period": profile.notice_period,
        "expected_salary": profile.expected_salary,
        "work_authorization": profile.work_authorization,
        "summary": profile.summary,
        "current_role": profile.current_role,
        "current_company": profile.current_company,
        "experience": profile.experience,
        "projects": profile.projects,
        "skills": profile.skills,
        "technologies": profile.technologies,
        "education": profile.education,
        "achievements": profile.achievements,
        "certifications": profile.certifications,
        "preferred_locations": profile.preferred_locations,
        "remote_preference": profile.remote_preference,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)
