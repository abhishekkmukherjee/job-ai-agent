import pytest
from pydantic import ValidationError

from app.ai.json_utils import extract_json
from app.schemas.ai import JobAnalysis, QuestionAnswer, QuestionAnswerBatch, QuickFilterResult, TailoredResume


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fences_and_prose():
    text = 'Sure! Here is the result:\n```json\n{"match_score": 88, "recommendation": "REVIEW"}\n```\nHope this helps.'
    assert extract_json(text)["match_score"] == 88


def test_extract_json_trailing_commas_and_nested():
    text = 'Result: {"a": [1, 2, 3,], "b": {"c": "d",},} trailing words'
    assert extract_json(text) == {"a": [1, 2, 3], "b": {"c": "d"}}


def test_extract_json_list_wrapped():
    assert extract_json('[{"question": "q", "answer": "a"}]') == {"items": [{"question": "q", "answer": "a"}]}


def test_extract_json_failure():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_job_analysis_validates_and_clamps():
    raw = {
        "match_score": 130, "recommendation": "apply", "experience_match": -5, "skill_match": "88",
        "role_match": 90, "location_match": 100, "salary_match": None, "reasoning": "single string",
        "missing_requirements": ["Kubernetes"], "red_flags": None, "confidence": 91, "extra_field": "ignored",
    }
    a = JobAnalysis.model_validate(raw)
    assert a.match_score == 100
    assert a.experience_match == 0
    assert a.skill_match == 88
    assert a.salary_match == 0
    assert a.reasoning == ["single string"]
    assert a.red_flags == []
    assert a.confidence == 0.91
    assert a.recommendation.value == "APPLY"


def test_job_analysis_recommendation_follows_score_not_model():
    a = JobAnalysis.model_validate({"match_score": 65, "recommendation": "APPLY"})
    a.enforce_recommendation_bands()
    assert a.recommendation.value == "LOW_PRIORITY"


def test_job_analysis_rejects_missing_score():
    with pytest.raises(ValidationError):
        JobAnalysis.model_validate({"recommendation": "APPLY"})


def test_job_analysis_rejects_unknown_recommendation():
    with pytest.raises(ValidationError):
        JobAnalysis.model_validate({"match_score": 80, "recommendation": "MAYBE"})


def test_quick_filter_bool_coercion():
    assert QuickFilterResult.model_validate({"relevant": "yes"}).relevant is True
    assert QuickFilterResult.model_validate({"relevant": "false", "confidence": 80}).confidence == 0.8


def test_question_answer_needs_review_default_and_batch():
    batch = QuestionAnswerBatch.model_validate(
        {"answers": [{"question": "Salary?", "answer": "", "confidence": 0.2, "needs_review": True}, {"question": "Why?", "answer": "Because"}]}
    )
    assert batch.answers[0].needs_review is True
    assert batch.answers[1].needs_review is False
    assert QuestionAnswer(question="q").confidence == 0.5


def test_tailored_resume_ignores_extra_and_defaults():
    r = TailoredResume.model_validate({"headline": "AI Engineer", "experience": [{"title": "Dev", "company": "X", "bullets": ["a"]}], "unknown": 1})
    assert r.experience[0].company == "X"
    assert r.skills == []
