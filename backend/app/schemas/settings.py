"""Editable runtime settings stored in the app_settings table."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FilterRules(BaseModel):
    """Rule-based pre-filter configuration (spec section 6)."""

    model_config = ConfigDict(extra="forbid")

    reject_title_keywords: list[str] = Field(
        default_factory=lambda: [
            "intern", "internship", "trainee", "apprentice", "unpaid", "volunteer",
            "director", "vp ", "vice president", "head of", "chief", "cto", "cio", "principal",
            "staff engineer", "distinguished",
            "recruiter", "sales", "marketing", "account executive", "customer success",
            "accountant", "nurse", "teacher", "driver", "designer", "ux ", "ui/ux",
            "product manager", "project manager", "scrum master", "qa ", "tester", "test engineer",
            "sdet", "support engineer", "helpdesk", "help desk", "technician",
            "salesforce", "sap ", "servicenow", "workday", "oracle ebs", "mainframe", "cobol", "abap",
            "php", "wordpress", "drupal", "magento", "android", "ios ", "flutter", "unity", "game",
            "embedded", "firmware", "hardware", "fpga", "vlsi", "network engineer", "sysadmin",
            "data entry", "content writer", "copywriter", "seo", "hr ", "human resources",
        ]
    )
    reject_description_keywords: list[str] = Field(default_factory=list)
    role_keywords: list[str] = Field(
        default_factory=lambda: [
            "ai engineer", "artificial intelligence", "generative ai", "genai", "gen ai", "llm",
            "machine learning", "ml engineer", "mlops", "deep learning", "nlp", "data scientist",
            "software engineer", "software developer", "backend", "back-end", "back end",
            "full stack", "full-stack", "fullstack", "python developer", "python engineer",
            "applied scientist", "applied ai", "founding engineer", "platform engineer",
            "node.js developer", "nodejs developer", "react developer", "web developer",
        ]
    )
    max_experience_years_over_profile: int = 3   # reject if job requires > profile + this
    min_experience_years_allowed: int = 0
    reject_if_onsite_outside_preferred_locations: bool = True
    reject_remote_outside_regions: bool = True   # remote roles restricted to other countries/regions
    treat_unknown_work_mode_as_onsite: bool = True  # unknown mode + location outside preferences -> reject
    allowed_remote_regions: list[str] = Field(
        default_factory=lambda: ["india", "worldwide", "anywhere", "global", "apac", "asia", "remote", "international"]
    )
    reject_companies: list[str] = Field(default_factory=list)   # merged with profile.companies_to_avoid
    prioritize_keywords: list[str] = Field(default_factory=list)
    max_job_age_days: int = 45
    treat_unknown_title_as: str = "unsure"   # unsure -> cheap AI filter, reject, pass


class CareerPageCompanies(BaseModel):
    """Company career pages that expose a public job-board API."""

    model_config = ConfigDict(extra="forbid")

    greenhouse: list[str] = Field(default_factory=list)   # board tokens, e.g. "anthropic"
    lever: list[str] = Field(default_factory=list)        # lever slugs, e.g. "mistral"
    ashby: list[str] = Field(default_factory=list)        # ashby slugs, e.g. "openai"


class SchedulerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cron: str = "0 8 * * *"
    timezone: str = "Asia/Kolkata"
    analyze: bool = True
    notify: bool = True


class AutoApplySettings(BaseModel):
    """Automatic submission - off by default.  Every guard must pass before a form is submitted."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    min_score: int = Field(default=85, ge=0, le=100)
    require_recommendation_apply: bool = False   # if True only APPLY (90+) jobs are auto-submitted
    daily_cap: int = Field(default=5, ge=0, le=100)
    allow_needs_review_answers: bool = False      # never submit answers the AI flagged for review
    blocked_domains: list[str] = Field(
        default_factory=lambda: [
            "linkedin.com", "naukri.com", "indeed.com", "glassdoor.com", "monster.com", "foundit.in",
            "shine.com", "instahyre.com", "hirist.com", "wellfound.com", "angel.co", "dice.com",
        ]
    )   # sites that require login / forbid automation: prepared for manual submission instead
    notify_each: bool = True
    email_enabled: bool = True                   # apply by email when a posting asks for CVs by mail
    email_per_company_days: int = Field(default=7, ge=0, le=90)


class RuntimeSettings(BaseModel):
    """Everything the user can tweak at runtime from the Settings page."""

    model_config = ConfigDict(extra="forbid")

    filter_rules: FilterRules = Field(default_factory=FilterRules)
    career_pages: CareerPageCompanies = Field(default_factory=CareerPageCompanies)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    auto_apply: AutoApplySettings = Field(default_factory=AutoApplySettings)
    enabled_sources: list[str] | None = None   # None -> use env JOB_SOURCES_ENABLED
    search_queries: list[str] = Field(default_factory=list)  # extra search terms beyond target roles
    min_score_to_show: int = 0


class RuntimeSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter_rules: FilterRules | None = None
    career_pages: CareerPageCompanies | None = None
    scheduler: SchedulerSettings | None = None
    auto_apply: AutoApplySettings | None = None
    enabled_sources: list[str] | None = None
    search_queries: list[str] | None = None
    min_score_to_show: int | None = None
