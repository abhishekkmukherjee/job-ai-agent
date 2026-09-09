from app.models.enums import (
    APPLICATION_TRANSITIONS,
    ApplicationStatus,
    Recommendation,
    can_transition,
    recommendation_for_score,
)


def test_every_status_has_transition_entry():
    for status in ApplicationStatus:
        assert status in APPLICATION_TRANSITIONS


def test_happy_path_transitions():
    path = [
        ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED, ApplicationStatus.APPROVED,
        ApplicationStatus.PREPARING, ApplicationStatus.READY_TO_APPLY, ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER,
    ]
    for cur, nxt in zip(path, path[1:]):
        assert can_transition(cur, nxt), f"{cur} -> {nxt}"


def test_cannot_skip_to_applied_from_discovered():
    assert not can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.APPLIED)
    assert not can_transition(ApplicationStatus.SHORTLISTED, ApplicationStatus.APPLIED)


def test_rejected_is_terminal():
    for s in ApplicationStatus:
        if s != ApplicationStatus.REJECTED:
            assert not can_transition(ApplicationStatus.REJECTED, s)


def test_same_status_is_noop_transition():
    assert can_transition(ApplicationStatus.APPLIED, ApplicationStatus.APPLIED)


def test_recommendation_bands():
    assert recommendation_for_score(100) == Recommendation.APPLY
    assert recommendation_for_score(90) == Recommendation.APPLY
    assert recommendation_for_score(89) == Recommendation.REVIEW
    assert recommendation_for_score(75) == Recommendation.REVIEW
    assert recommendation_for_score(74) == Recommendation.LOW_PRIORITY
    assert recommendation_for_score(60) == Recommendation.LOW_PRIORITY
    assert recommendation_for_score(59) == Recommendation.REJECT
    assert recommendation_for_score(0) == Recommendation.REJECT
