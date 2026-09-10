"""Apply-by-email detection/sending guards and the location priority helper."""
from __future__ import annotations

from email import message_from_bytes

from sqlalchemy import select

from app.config import Settings
from app.models import Job, Profile, RemoteType
from app.services.email_apply import EmailApplier, find_application_email
from app.services.location import describe_priority, location_matches, location_rank


def test_find_application_email_prefers_apply_addresses():
    text = "About us... Questions? privacy@acme.com. To apply, send your resume to careers@acme.com with the subject 'AI Engineer'."
    assert find_application_email(text) == "careers@acme.com"
    assert find_application_email("Contact noreply@acme.com for nothing") is None
    assert find_application_email("Interested? Mail your CV at hr@beta.in") == "hr@beta.in"
    assert find_application_email("We are hiring. Our office: info@example.com") is None
    assert find_application_email("Our newsletter: news@gamma.io") is None   # no apply hint, no hiring words


def test_email_applier_sends_pdf_and_uses_gmail_creds(tmp_path, monkeypatch):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    sent = {}

    def fake_deliver(host, port, user, password, use_tls, msg):
        sent.update({"host": host, "port": port, "user": user, "tls": use_tls, "msg": msg})

    monkeypatch.setattr(EmailApplier, "_deliver", staticmethod(fake_deliver))
    assert not EmailApplier(Settings(imap_host="imap.gmail.com", imap_user="me@gmail.com", imap_password="app-pass", smtp_host="")).is_configured()  # read-only by default
    applier = EmailApplier(Settings(imap_host="imap.gmail.com", imap_user="me@gmail.com", imap_password="app-pass", smtp_host="", smtp_use_imap_account=True))
    assert applier.is_configured()
    result = applier.send("hr@acme.com", "Application: AI Engineer", "Hello", str(pdf), reply_to="me@gmail.com")
    assert result["channel"] == "email" and result["to"] == "hr@acme.com"
    assert sent["host"] == "smtp.gmail.com" and sent["port"] == 587 and sent["user"] == "me@gmail.com" and sent["tls"] is True
    msg = sent["msg"]
    assert msg["To"] == "hr@acme.com" and msg["From"] == "me@gmail.com" and msg["Reply-To"] == "me@gmail.com"
    parsed = message_from_bytes(bytes(msg))
    attachments = [p.get_filename() for p in parsed.walk() if p.get_filename()]
    assert attachments == ["resume.pdf"]
    assert not EmailApplier(Settings(smtp_host="", imap_host="", imap_user="", imap_password="")).is_configured()


def test_location_rank_follows_profile_order(db):
    profile = db.execute(select(Profile)).scalars().one()
    profile.target_locations = ["Bangalore", "Pune", "Hyderabad", "Mumbai", "Remote"]
    profile.preferred_locations = []

    def job(location, remote=RemoteType.UNKNOWN):
        return Job(external_id="x", source="t", title="t", location=location, remote_type=remote)

    assert location_rank(job("Bengaluru, Karnataka"), profile) == 0
    assert location_rank(job("Pune (Hybrid)"), profile) == 1
    assert location_rank(job("Hyderabad"), profile) == 2
    assert location_rank(job("Navi Mumbai"), profile) == 3
    assert location_rank(job("Remote - India", RemoteType.REMOTE), profile) == 4
    assert location_rank(job("Berlin"), profile) == 6
    assert location_matches("Gurugram, Haryana", "Delhi NCR") and location_matches("Kolkata", "kolkata")
    assert describe_priority(profile).startswith("Bangalore > Pune > Hyderabad")
