# Build: Personal AI Job Application Agent

Build a production-quality MVP of a personal AI job-search and application assistant.

## Goal

Create an application that automatically discovers relevant jobs from multiple job sources, evaluates them against my profile, generates tailored application material, tracks applications, and assists with filling application forms.

The system should minimize my manual work while keeping **final job submission under my control initially**.

I have:

* Gemini API access with free-tier quota
* OpenRouter API access, including free models
* Ability to run a small Node.js/Python backend
* GitHub account
* Ability to deploy on free/low-cost infrastructure such as Cloudflare

The architecture should therefore prioritize **zero or near-zero monthly cost**.

---

# 1. Core workflow

The complete workflow should be:

```text
Scheduled Job Search
        ↓
Collect New Jobs
        ↓
Normalize Job Data
        ↓
Remove Duplicates
        ↓
Basic Rule-Based Filtering
        ↓
LLM Job Analysis
        ↓
Match Against My Profile
        ↓
Score Jobs 0–100
        ↓
Select High-Quality Jobs
        ↓
Generate Tailored Application Material
        ↓
Show Jobs in Dashboard
        ↓
User Approves Application
        ↓
Browser Automation
        ↓
Fill Application Form
        ↓
User Reviews
        ↓
User Manually Submits
        ↓
Track Application
```

Do NOT start with fully autonomous submission.

The initial version must require human confirmation before submitting an application.

---

# 2. Tech stack

Use a practical stack that is easy to deploy and maintain.

Preferred:

### Backend

* Python
* FastAPI
* Pydantic
* SQLAlchemy

### Database

Use SQLite locally.

Design the database layer so it can later be switched to PostgreSQL or Cloudflare D1.

### AI

Create a provider abstraction:

```text
AIProvider
├── GeminiProvider
└── OpenRouterProvider
```

The application must not be tightly coupled to either provider.

Environment variables:

```env
GEMINI_API_KEY=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
DATABASE_URL=
```

Implement configurable model routing.

For example:

```text
Simple extraction/classification
        ↓
OpenRouter/free model

Complex job matching
        ↓
Gemini

Resume/application generation
        ↓
Gemini

Fallback
        ↓
OpenRouter
```

The exact model names should be configurable through environment variables rather than hardcoded.

---

# 3. User profile

Create a profile system containing:

### Personal information

* Name
* Email
* Phone
* Current location
* Preferred locations
* LinkedIn
* GitHub
* Portfolio
* Years of experience
* Notice period
* Expected salary

### Professional profile

* Current role
* Previous roles
* Companies
* Projects
* Skills
* Technologies
* Education
* Achievements
* Certifications

### Job preferences

* Target roles
* Target locations
* Remote/hybrid/onsite preference
* Minimum salary
* Experience range
* Preferred industries
* Companies to avoid
* Keywords to prioritize
* Keywords to reject

Do not hardcode my profile into application logic.

Create a profile configuration/database record that I can edit.

---

# 4. Initial profile data

Seed the development database with this profile:

Name:
Abhishek Mukherjee

Target roles:

* AI Engineer
* Generative AI Engineer
* Machine Learning Engineer
* Software Engineer
* Backend Engineer
* Full-Stack Engineer

Experience:
Approximately 3 years

Skills include:

* Python
* JavaScript
* TypeScript
* Node.js
* Next.js
* React
* FastAPI
* PostgreSQL
* AWS
* RAG
* LLM applications
* LLM fine-tuning
* LoRA
* Computer Vision
* AI APIs
* Vector databases
* AI agents
* AI evaluation
* Backend systems
* Production web applications

Preferred locations:

* Bangalore
* Remote

Use this only as seed data. Make it editable.

---

# 5. Job discovery

Build a modular job-source architecture.

```text
JobSource
├── SourceA
├── SourceB
├── SourceC
└── CompanyCareerPages
```

Each source should return a normalized structure:

```json
{
  "external_id": "",
  "source": "",
  "title": "",
  "company": "",
  "location": "",
  "remote_type": "",
  "salary_min": null,
  "salary_max": null,
  "description": "",
  "url": "",
  "posted_at": null
}
```

Start with sources that can legally/reliably be accessed without bypassing CAPTCHAs, authentication restrictions, or anti-bot protections.

Do NOT implement CAPTCHA bypassing.

Do NOT implement stealth techniques designed to evade anti-bot detection.

If a source cannot be reliably automated, create a connector interface and document the limitation.

---

# 6. Job filtering

Before using an LLM, perform cheap rule-based filtering.

Examples:

Reject:

* Internships
* Roles requiring substantially more experience than the profile
* Completely unrelated roles
* Locations outside preferences when onsite
* Duplicate jobs
* Previously rejected jobs

Prioritize:

* AI Engineer
* GenAI Engineer
* ML Engineer
* Backend Engineer
* Software Engineer
* Full-Stack Engineer

Make the filtering rules configurable.

---

# 7. AI job evaluation

Create a structured LLM evaluation.

The LLM should return JSON like:

```json
{
  "match_score": 91,
  "recommendation": "APPLY",
  "experience_match": 90,
  "skill_match": 95,
  "role_match": 95,
  "location_match": 100,
  "salary_match": 80,
  "reasoning": [
    "Strong match for LLM/RAG experience",
    "Backend experience aligns with requirements",
    "AWS experience matches infrastructure requirements"
  ],
  "missing_requirements": [
    "Kubernetes"
  ],
  "red_flags": [],
  "confidence": 0.91
}
```

Recommendations:

```text
90–100 = APPLY
75–89  = REVIEW
60–74  = LOW PRIORITY
0–59   = REJECT
```

Do not let the LLM make decisions outside the returned structured schema.

Validate all AI responses with Pydantic.

---

# 8. Resume tailoring

Maintain a master resume/profile.

For a selected job, the AI should generate a tailored resume based ONLY on facts contained in the master profile.

Critical rule:

## NEVER invent experience.

Do not invent:

* Companies
* Job titles
* Years of experience
* Projects
* Technologies
* Metrics
* Certifications
* Achievements

If a metric is not available, do not fabricate one.

The AI can:

* Reorder skills
* Rephrase existing experience
* Highlight relevant projects
* Select relevant bullets
* Improve wording
* Change emphasis based on job requirements

---

# 9. Application question agent

When an application contains questions, send the question plus relevant profile information to the AI.

Generate answers for:

* Why do you want this role?
* Why this company?
* Tell us about yourself
* Relevant experience
* AI/ML experience
* Backend experience
* Salary expectations
* Notice period
* Relocation
* Work authorization

Answers must be grounded in the profile.

Never fabricate information.

Return:

```json
{
  "question": "",
  "answer": "",
  "confidence": 0.95,
  "needs_review": false
}
```

If the question requires information that does not exist in the profile:

```json
{
  "needs_review": true
}
```

---

# 10. Browser automation

Use Playwright.

The browser agent should:

1. Open the application URL.
2. Inspect the page.
3. Identify form fields.
4. Map fields to profile data.
5. Fill safe fields.
6. Upload the selected resume.
7. Generate answers for text questions.
8. Stop before final submission.

Show a review screen:

```text
Application Ready

Company: XYZ
Role: AI Engineer

Fields filled: 14
Questions answered: 5
Resume: tailored_resume.pdf

[Open Application]
[Review Answers]
[Fill Application]
[Cancel]
```

After filling:

```text
Application filled successfully.

DO NOT SUBMIT automatically.

[Open Browser]
[Submit Manually]
```

The user should remain responsible for final submission.

---

# 11. Application tracker

Create statuses:

```text
DISCOVERED
SHORTLISTED
APPROVED
PREPARING
READY_TO_APPLY
APPLIED
INTERVIEW
REJECTED
OFFER
WITHDRAWN
```

Store:

* Company
* Role
* Job URL
* Source
* Match score
* Application date
* Resume version
* Answers
* Status
* Notes
* Follow-up date
* Interview dates
* Rejection reason

Prevent duplicate applications.

---

# 12. Dashboard

Build a simple clean web dashboard.

Dashboard should show:

```text
Today's Search

Jobs discovered: 87
Strong matches: 12
Recommended applications: 7
Applications submitted: 3
Interviews: 1
```

Job cards:

```text
AI Engineer
Company XYZ
Bangalore / Remote

Match: 94%

Skills:
✓ Python
✓ RAG
✓ LLM
✓ AWS
✓ FastAPI

Missing:
Kubernetes

Recommendation:
APPLY

[View Job]
[Tailor Resume]
[Prepare Application]
```

Add filters:

* Match score
* Role
* Location
* Remote
* Company
* Status
* Source

---

# 13. Scheduler

Implement scheduled job discovery.

Example:

```text
Every morning at 8:00 AM
        ↓
Search jobs
        ↓
Process jobs
        ↓
Evaluate matches
        ↓
Notify user
```

The scheduler must be configurable.

Do not hardcode scheduling logic into the application.

---

# 14. Notifications

Implement a notification abstraction:

```text
NotificationProvider
├── Email
├── Telegram
└── Console
```

For MVP, console + email is sufficient.

Notification example:

```text
Job Agent — Daily Report

47 new jobs found

8 strong matches

Top opportunities:

1. AI Engineer — Company A — 94%
2. GenAI Engineer — Company B — 92%
3. Backend Engineer — Company C — 89%

Open dashboard:
http://localhost:3000
```

---

# 15. AI cost optimization

This is extremely important.

The application should minimize LLM calls.

Use:

```text
Rules first
    ↓
Cheap model second
    ↓
Strong model only when necessary
```

Cache AI results.

Never analyze the same job repeatedly.

Store:

```text
job_hash
profile_version
model
prompt_version
result
timestamp
```

If the job and profile have not changed, reuse the previous result.

Implement rate-limit handling.

If Gemini fails:

```text
Gemini
 ↓
OpenRouter
 ↓
Retry with exponential backoff
```

Do not enter infinite retry loops.

---

# 16. Prompt management

Do not scatter prompts throughout the code.

Create:

```text
/prompts
    job_analysis.txt
    resume_tailoring.txt
    application_questions.txt
    job_filtering.txt
```

Version prompts.

Example:

```text
JOB_ANALYSIS_PROMPT_VERSION=1
```

---

# 17. Security

Never commit:

```text
.env
API keys
cookies
session tokens
browser profiles
credentials
```

Add `.env.example`.

Sanitize user-controlled job descriptions before rendering them.

Do not execute arbitrary JavaScript from job descriptions.

Keep browser automation isolated.

---

# 18. Logging

Implement structured logging.

Log:

```text
JOB_DISCOVERED
JOB_FILTERED
AI_ANALYSIS_STARTED
AI_ANALYSIS_COMPLETED
APPLICATION_STARTED
APPLICATION_FILLED
APPLICATION_FAILED
```

Never log API keys, passwords, cookies, or authentication tokens.

---

# 19. Error handling

The application should continue if one job fails.

Example:

```text
100 jobs
 ↓
3 failed
 ↓
97 successfully processed
```

Do not terminate the entire pipeline because of one bad job.

Store failures for debugging.

---

# 20. Testing

Create tests for:

### Unit tests

* Job normalization
* Duplicate detection
* Match scoring
* Profile matching
* AI JSON validation
* Filtering
* Application status transitions

### Integration tests

* Gemini provider
* OpenRouter provider
* Database
* Job pipeline

### Browser tests

Create a local fake application website with fields such as:

```text
Name
Email
Phone
Resume
Experience
Why do you want this role?
Salary
Notice period
```

Use this fake site to test Playwright without depending on external websites.

---

# 21. Project structure

Use something similar to:

```text
job-agent/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── agents/
│   │   ├── ai/
│   │   ├── browser/
│   │   ├── jobs/
│   │   ├── models/
│   │   ├── services/
│   │   ├── notifications/
│   │   ├── scheduler/
│   │   └── main.py
│   │
│   └── tests/
│
├── frontend/
│   └── ...
│
├── prompts/
│   ├── job_analysis.txt
│   ├── resume_tailoring.txt
│   └── application_questions.txt
│
├── fake-job-site/
│
├── scripts/
│
├── .env.example
├── docker-compose.yml
├── README.md
└── requirements.txt
```

You may adjust this structure if you have a better architecture, but keep responsibilities separated.

---

# 22. API endpoints

Implement APIs such as:

```text
GET    /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs/search
POST   /api/jobs/{id}/analyze
POST   /api/jobs/{id}/tailor-resume

GET    /api/applications
POST   /api/applications
PATCH  /api/applications/{id}

GET    /api/profile
PATCH  /api/profile

POST   /api/applications/{id}/prepare
POST   /api/applications/{id}/fill

GET    /api/dashboard
```

Use proper validation and error responses.

---

# 23. Frontend

Use a simple modern UI.

Do NOT over-engineer the frontend.

Prioritize:

1. Jobs
2. Match scores
3. Application preparation
4. Application tracker
5. Profile
6. Settings

A clean dashboard is more important than animations.

---

# 24. Deployment

Make the application deployable using free/cheap infrastructure.

Provide:

### Local development

```bash
docker compose up
```

or equivalent.

### Production

Document deployment options such as:

```text
Frontend → Cloudflare Pages
Backend → Cloudflare-compatible deployment or free/low-cost server
Database → SQLite initially / D1/Postgres later
Scheduler → Cloudflare Cron / GitHub Actions
```

The system should work locally even if cloud deployment is not configured.

---

# 25. Important safety/reliability constraints

Do NOT:

* bypass CAPTCHA
* bypass authentication
* bypass anti-bot systems
* evade rate limits
* create fake identities
* fabricate resume information
* fabricate application answers
* automatically submit applications without user approval
* spam the same company
* submit duplicate applications

Respect the policies and terms of the job platforms being accessed.

Build connectors in a modular way so unsupported platforms can be disabled.

---

# 26. Development approach

Do NOT attempt to build everything at once.

Build in phases.

## Phase 1 — Foundation

Implement:

* Project structure
* Database
* Profile
* Job model
* Application model
* Basic API
* Dashboard

Make sure it runs.

## Phase 2 — AI

Implement:

* Gemini provider
* OpenRouter provider
* Provider abstraction
* Job analysis
* Match scoring
* AI caching
* Structured outputs

Test with sample jobs.

## Phase 3 — Job discovery

Implement:

* Job source abstraction
* First working source
* Normalization
* Deduplication
* Filtering

## Phase 4 — Application preparation

Implement:

* Resume tailoring
* Application question generation
* Review interface

## Phase 5 — Browser automation

Implement:

* Playwright
* Fake local application website
* Form detection
* Profile field mapping
* Resume upload
* Question answering
* Stop before submission

## Phase 6 — Scheduler + notifications

Implement:

* Scheduled searches
* Daily report
* Notifications

## Phase 7 — Production hardening

Implement:

* Error handling
* Logging
* Tests
* Security
* Deployment documentation

---

# 27. Coding principles

Write real working code.

Do not create placeholder functions such as:

```python
# TODO implement later
```

unless the feature genuinely depends on an external service that is not yet configured.

Prefer simple reliable architecture over unnecessary "AI agent" complexity.

Use normal deterministic code wherever possible.

Use an LLM only where reasoning/language understanding is actually useful.

Every AI output must be schema-validated.

Every external API call must have timeout/error handling.

---

# 28. First task

Start by inspecting the environment and then build **Phase 1 completely**.

Before moving to Phase 2:

1. Create the project.
2. Create the database.
3. Create the profile model.
4. Create the job model.
5. Create the application model.
6. Create FastAPI endpoints.
7. Create the frontend dashboard.
8. Seed my profile.
9. Add sample jobs.
10. Make the dashboard display those jobs.
11. Add tests.
12. Run the application.
13. Fix all errors.
14. Update README with exact commands to run it.

Then proceed to Phase 2 automatically if Phase 1 is working.

Do not stop after creating a plan.

**Actually implement the application, run it, test it, and fix errors.**
