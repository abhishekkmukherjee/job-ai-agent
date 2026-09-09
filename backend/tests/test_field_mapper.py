from sqlalchemy import select

from app.browser.field_mapper import FormField, looks_like_question, map_fields, match_existing_answer
from app.models import Profile


def ff(label="", kind="text", **kw) -> FormField:
    return FormField(selector=f"[data-jobagent-idx='{abs(hash(label + kind)) % 1000}']", kind=kind, label=label, **kw)


def test_map_fields_covers_common_fields(db):
    profile = db.execute(select(Profile)).scalars().one()
    profile.email, profile.phone, profile.notice_period, profile.expected_salary = "a@b.com", "+91 99999", "30 days", "25 LPA"
    profile.linkedin_url, profile.current_company = "https://linkedin.com/in/abhishek", "Acme"
    fields = [
        ff("First name"), ff("Last name"), ff("Email address", "email"), ff("Phone number", "tel"),
        ff("Current location (city)"), ff("LinkedIn profile URL", "url"), ff("GitHub profile", "url"),
        ff("Resume / CV (PDF)", "file", accept=".pdf"), ff("Years of experience", "number"), ff("Current company"),
        ff("Notice period", "select", options=["Select...", "Immediate", "15 days", "30 days", "60 days"]),
        ff("Expected salary (annual)"),
        ff("Are you legally authorized to work in India?", "select", options=["Select...", "Yes", "No"]),
        ff("Why do you want this role?", "textarea"), ff("Tell us about yourself", "textarea"),
        ff("I agree to the privacy policy", "checkbox"), ff("Gender", "select", options=["Male", "Female"]),
        ff("Password", "password"),
    ]
    actions, questions, unmatched = map_fields(fields, profile, "C:/tmp/resume.pdf")
    by_label = {a.field.label: a for a in actions}
    assert by_label["First name"].value == "Abhishek" and by_label["Last name"].value == "Mukherjee"
    assert by_label["Email address"].value == "a@b.com" and by_label["Phone number"].value == "+91 99999"
    assert by_label["Current location (city)"].value == "Bangalore, India"
    assert by_label["LinkedIn profile URL"].value.startswith("https://linkedin")
    assert by_label["GitHub profile"].status == "skipped"  # empty in profile
    assert by_label["Resume / CV (PDF)"].action == "upload"
    assert by_label["Years of experience"].value == "3"
    assert by_label["Current company"].value == "Acme"
    assert by_label["Notice period"].action == "select" and by_label["Notice period"].value == "30 days"
    assert by_label["Expected salary (annual)"].value == "25 LPA"
    assert [q.label for q in questions] == ["Why do you want this role?", "Tell us about yourself"]
    unmatched_labels = {f.label for f in unmatched}
    assert "Gender" in unmatched_labels
    assert by_label["I agree to the privacy policy"].action == "check"  # consent needed to submit; marketing boxes stay unticked
    assert "Password" not in unmatched_labels and "Password" not in by_label


def test_looks_like_question_and_answer_matching():
    assert looks_like_question(ff("Why do you want to work here?", "textarea"))
    assert looks_like_question(ff("Cover letter", "textarea"))
    assert not looks_like_question(ff("Address line 1"))
    answers = [
        {"question": "Why do you want this role?", "answer": "Because AI.", "needs_review": False},
        {"question": "Salary", "answer": "", "needs_review": True},
    ]
    assert match_existing_answer("Why do you want this role", answers)["answer"] == "Because AI."
    assert match_existing_answer("why do you want the role?", answers)["answer"] == "Because AI."
    assert match_existing_answer("Describe a conflict with a coworker", answers) is None
    assert match_existing_answer("Salary", answers) is None  # empty answers never match
