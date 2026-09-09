"""Shared enumerations used by models and schemas."""
from __future__ import annotations

import enum


class RemoteType(str, enum.Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class JobPipelineStatus(str, enum.Enum):
    NEW = "NEW"                      # discovered, not yet filtered
    REJECTED_BY_RULES = "REJECTED_BY_RULES"
    REJECTED_BY_AI_FILTER = "REJECTED_BY_AI_FILTER"
    PENDING_ANALYSIS = "PENDING_ANALYSIS"
    ANALYZED = "ANALYZED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class JobUserAction(str, enum.Enum):
    NONE = "NONE"
    SHORTLISTED = "SHORTLISTED"
    DISMISSED = "DISMISSED"


class Recommendation(str, enum.Enum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    LOW_PRIORITY = "LOW_PRIORITY"
    REJECT = "REJECT"


class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    SHORTLISTED = "SHORTLISTED"
    APPROVED = "APPROVED"
    PREPARING = "PREPARING"
    READY_TO_APPLY = "READY_TO_APPLY"
    APPLIED = "APPLIED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    OFFER = "OFFER"
    WITHDRAWN = "WITHDRAWN"


# Allowed status transitions for the application tracker.
APPLICATION_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: {ApplicationStatus.SHORTLISTED, ApplicationStatus.APPROVED, ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED},
    ApplicationStatus.SHORTLISTED: {ApplicationStatus.APPROVED, ApplicationStatus.WITHDRAWN, ApplicationStatus.DISCOVERED, ApplicationStatus.REJECTED},
    ApplicationStatus.APPROVED: {ApplicationStatus.PREPARING, ApplicationStatus.READY_TO_APPLY, ApplicationStatus.WITHDRAWN, ApplicationStatus.SHORTLISTED},
    ApplicationStatus.PREPARING: {ApplicationStatus.READY_TO_APPLY, ApplicationStatus.APPROVED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.READY_TO_APPLY: {ApplicationStatus.APPLIED, ApplicationStatus.PREPARING, ApplicationStatus.APPROVED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.APPLIED: {ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED, ApplicationStatus.OFFER, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.INTERVIEW: {ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED, ApplicationStatus.OFFER, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.OFFER: {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.WITHDRAWN: {ApplicationStatus.DISCOVERED},
}


def can_transition(current: ApplicationStatus, new: ApplicationStatus) -> bool:
    if current == new:
        return True
    return new in APPLICATION_TRANSITIONS.get(current, set())


class SearchRunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def recommendation_for_score(score: int) -> Recommendation:
    """Deterministic mapping from match score to recommendation (spec section 7)."""
    if score >= 90:
        return Recommendation.APPLY
    if score >= 75:
        return Recommendation.REVIEW
    if score >= 60:
        return Recommendation.LOW_PRIORITY
    return Recommendation.REJECT
