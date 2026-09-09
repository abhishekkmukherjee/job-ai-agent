"""Seed data: the initial profile (editable afterwards) and a handful of sample jobs.

The profile below is *seed data only* - it is inserted once and then owned by the
database.  Application logic never reads these constants directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .jobs.dedupe import content_hash
from .logging_config import get_logger
from .models import Job, JobPipelineStatus, Profile, RemoteType

logger = get_logger(__name__)

SEED_PROFILE: dict = {
    "full_name": "Abhishek Mukherjee",
    "email": "",
    "phone": "",
    "current_location": "Bangalore, India",
    "preferred_locations": ["Bangalore", "Remote"],
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "years_of_experience": 3,
    "notice_period": "",
    "expected_salary": "",
    "work_authorization": "Indian citizen; authorized to work in India",
    "summary": (
        "Software engineer with approximately 3 years of experience building production web "
        "applications and AI/LLM-powered systems: RAG pipelines, LLM fine-tuning (LoRA), AI agents, "
        "computer vision and backend services on AWS."
    ),
    "current_role": "AI / Software Engineer",
    "current_company": "",
    "experience": [
        {
            "title": "AI / Software Engineer",
            "company": "(fill in from your resume)",
            "start": "",
            "end": "Present",
            "location": "Bangalore",
            "bullets": [
                "Built production LLM applications including RAG pipelines and AI agents",
                "Fine-tuned LLMs with LoRA for domain specific tasks",
                "Developed backend services with Python/FastAPI and Node.js on AWS",
                "Built full-stack features with React / Next.js and PostgreSQL",
            ],
            "technologies": ["Python", "FastAPI", "Node.js", "React", "Next.js", "PostgreSQL", "AWS"],
        }
    ],
    "projects": [
        {
            "name": "AI Job Application Agent",
            "description": "Personal AI assistant that discovers jobs, scores them against a profile with LLMs and prepares applications.",
            "technologies": ["Python", "FastAPI", "SQLAlchemy", "Gemini", "OpenRouter", "Playwright", "React"],
            "url": "",
            "bullets": [],
        }
    ],
    "skills": [
        "Python", "JavaScript", "TypeScript", "Node.js", "Next.js", "React", "FastAPI", "PostgreSQL", "AWS",
        "RAG", "LLM applications", "LLM fine-tuning", "LoRA", "Computer Vision", "AI APIs", "Vector databases",
        "AI agents", "AI evaluation", "Backend systems", "Production web applications",
    ],
    "technologies": ["Python", "TypeScript", "FastAPI", "Node.js", "React", "Next.js", "PostgreSQL", "AWS", "Docker", "Git"],
    "education": [],
    "achievements": [],
    "certifications": [],
    "target_roles": [
        "AI Engineer", "Generative AI Engineer", "Machine Learning Engineer",
        "Software Engineer", "Backend Engineer", "Full-Stack Engineer",
    ],
    "target_locations": ["Bangalore", "Remote"],
    "remote_preference": "any",
    "minimum_salary": None,
    "salary_currency": "INR",
    "experience_min": 1,
    "experience_max": 6,
    "preferred_industries": ["AI", "SaaS", "Developer tools", "Fintech", "Healthtech"],
    "companies_to_avoid": [],
    "keywords_prioritize": ["LLM", "RAG", "GenAI", "Python", "FastAPI", "AWS", "agents"],
    "keywords_reject": ["internship", "unpaid", "commission only"],
}


def _sample_jobs() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "title": "AI Engineer (LLM Applications)",
            "company": "Nimbus Labs",
            "location": "Bangalore, India (Hybrid)",
            "remote_type": RemoteType.HYBRID,
            "salary_min": 2500000, "salary_max": 4000000, "salary_currency": "INR",
            "url": "https://example.com/jobs/nimbus-ai-engineer",
            "posted_at": now - timedelta(days=1),
            "tags": ["python", "llm", "rag", "aws"],
            "description": (
                "We are building LLM-powered products for enterprise customers.\n\n"
                "Responsibilities:\n- Design and ship RAG pipelines and AI agents in production\n"
                "- Evaluate LLM outputs and build evaluation harnesses\n- Own backend services (Python, FastAPI) on AWS\n\n"
                "Requirements:\n- 2-5 years of software engineering experience\n- Strong Python\n"
                "- Experience with vector databases and LLM APIs (OpenAI, Gemini)\n- Nice to have: Kubernetes, LoRA fine-tuning"
            ),
        },
        {
            "title": "Generative AI Engineer",
            "company": "Orbital Health",
            "location": "Remote (India)",
            "remote_type": RemoteType.REMOTE,
            "salary_min": None, "salary_max": None, "salary_currency": "",
            "url": "https://example.com/jobs/orbital-genai",
            "posted_at": now - timedelta(days=2),
            "tags": ["genai", "python", "fine-tuning"],
            "description": (
                "Join our applied AI team to fine-tune and deploy LLMs for clinical workflows.\n\n"
                "You will: fine-tune open models with LoRA/QLoRA, build retrieval systems, and integrate with our Next.js frontend.\n"
                "Must have: 3+ years experience, Python, PyTorch or HF transformers, PostgreSQL. Bonus: healthcare experience."
            ),
        },
        {
            "title": "Backend Engineer - Python",
            "company": "Ledgerly",
            "location": "Bangalore",
            "remote_type": RemoteType.ONSITE,
            "salary_min": 1800000, "salary_max": 3000000, "salary_currency": "INR",
            "url": "https://example.com/jobs/ledgerly-backend",
            "posted_at": now - timedelta(days=3),
            "tags": ["python", "fastapi", "postgresql", "aws"],
            "description": (
                "Fintech startup looking for a backend engineer with 2-4 years experience.\n"
                "Stack: Python, FastAPI, PostgreSQL, Redis, AWS (ECS, RDS). You will design APIs, "
                "optimize queries and own reliability. Experience with Kubernetes is a plus."
            ),
        },
        {
            "title": "Senior Machine Learning Engineer",
            "company": "Quantiva",
            "location": "Remote",
            "remote_type": RemoteType.REMOTE,
            "salary_min": None, "salary_max": None, "salary_currency": "",
            "url": "https://example.com/jobs/quantiva-mle",
            "posted_at": now - timedelta(days=5),
            "tags": ["ml", "mlops", "kubernetes"],
            "description": (
                "We need a senior MLE with 7+ years of experience to lead our recommendation platform. "
                "Requirements: Spark, Kubernetes, feature stores, Go or Java. Deep learning experience required."
            ),
        },
        {
            "title": "Full-Stack Engineer (Next.js / Node.js)",
            "company": "Brightpath",
            "location": "Remote - Worldwide",
            "remote_type": RemoteType.REMOTE,
            "salary_min": 40000, "salary_max": 70000, "salary_currency": "USD",
            "url": "https://example.com/jobs/brightpath-fullstack",
            "posted_at": now - timedelta(days=1),
            "tags": ["react", "nextjs", "node", "typescript"],
            "description": (
                "Remote-first ed-tech company. Build product features end to end with Next.js, TypeScript, Node.js and PostgreSQL. "
                "We are integrating AI tutoring features (OpenAI APIs, RAG) - experience there is a big plus. 2+ years experience."
            ),
        },
        {
            "title": "Machine Learning Intern",
            "company": "DataSprout",
            "location": "Bangalore",
            "remote_type": RemoteType.ONSITE,
            "salary_min": None, "salary_max": None, "salary_currency": "",
            "url": "https://example.com/jobs/datasprout-intern",
            "posted_at": now - timedelta(days=4),
            "tags": ["internship"],
            "description": "6 month internship for final year students. Python, pandas, scikit-learn.",
        },
        {
            "title": "Software Engineer, AI Platform",
            "company": "Helix Systems",
            "location": "Pune, India",
            "remote_type": RemoteType.ONSITE,
            "salary_min": None, "salary_max": None, "salary_currency": "",
            "url": "https://example.com/jobs/helix-ai-platform",
            "posted_at": now - timedelta(days=6),
            "tags": ["python", "aws", "llm"],
            "description": (
                "Build the platform that serves LLM features to thousands of users. Python, AWS, Docker, "
                "vector databases. 2-6 years experience. Onsite in Pune."
            ),
        },
    ]


def seed_profile(db: Session) -> Profile:
    existing = db.execute(select(Profile)).scalars().first()
    if existing is not None:
        return existing
    profile = Profile(**SEED_PROFILE)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    logger.info("Seeded profile for %s", profile.full_name)
    return profile


def seed_sample_jobs(db: Session) -> int:
    # Samples only make sense in an empty database; never mix them into real discovered jobs.
    if db.execute(select(Job.id).limit(1)).first() is not None:
        return 0
    created = 0
    for idx, data in enumerate(_sample_jobs(), start=1):
        external_id = f"sample-{idx}"
        job = Job(
            external_id=external_id,
            source="sample",
            content_hash=content_hash(data["title"], data["company"]),
            pipeline_status=JobPipelineStatus.NEW,
            is_sample=True,
            **data,
        )
        db.add(job)
        created += 1
    db.commit()
    logger.info("Seeded %d sample jobs", created)
    return created


def seed_all(db: Session, with_sample_jobs: bool = True) -> None:
    seed_profile(db)
    if with_sample_jobs:
        seed_sample_jobs(db)
