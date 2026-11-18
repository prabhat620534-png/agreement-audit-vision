"""Offline tests - no API key or network needed. The vision model is mocked."""
from pathlib import Path

import pytest

from agreement_audit import pipeline
from agreement_audit.download import direct_url, drive_id, file_kind
from agreement_audit.pipeline import audit_document
from agreement_audit.society_name import clean_name, name_hint
from agreement_audit.vision import parse_reply

SAMPLES = Path(__file__).parent.parent / "samples"


# ---------- parsing messy LLM output ----------
def test_parse_reply_clean_json():
    r = parse_reply('{"society_name": "Green Meadows CHSL", "is_stamped": "Yes", "is_signed": "No"}')
    assert r == {"society_name": "Green Meadows CHSL", "name_box_filled": None, "is_stamped": "Yes", "is_signed": "No"}


def test_parse_reply_markdown_and_chatter():
    r = parse_reply('Sure! Here it is:\n```json\n{"is_stamped": "yes", "is_signed": "NO"}\n```')
    assert r["is_stamped"] == "Yes" and r["is_signed"] == "No"


def test_parse_reply_broken_json_falls_back_to_regex():
    r = parse_reply('{"society_name": "Lakeview", "is_stamped": Yes, "is_signed": "No"')
    assert r["society_name"] == "Lakeview" and r["is_stamped"] == "Yes" and r["is_signed"] == "No"


def test_unanswered_field_is_none_not_no():
    assert parse_reply('{"society_name": "X Y Z"}')["is_signed"] is None


# ---------- guardrails on names ----------
@pytest.mark.parametrize("bad", ["Not listed", "N/A", "Acme Services Pvt. Ltd.", "Sorry, I cannot read the image",
                                 "City: Bengaluru", "", "12345"])
def test_clean_name_rejects(bad):
    assert clean_name(bad) is None


def test_clean_name_strips_label():
    assert clean_name("Name of society (customer): Green Meadows CHSL") == "Green Meadows CHSL"


def test_name_hint_from_messy_file_name():
    assert name_hint("Green Meadows B wing -1--3f2a9c1e-0b7d-4e55-9a11-2c3d4e5f6a7b.pdf") == "Green Meadows B wing"


# ---------- links ----------
def test_viewer_link_unwrapped_without_double_encoding():
    u = direct_url("https://docs.google.com/viewer?url=https://cdn.example.com/files/Green%20Meadows.pdf&embedded=true")
    assert u == "https://cdn.example.com/files/Green%20Meadows.pdf"


def test_drive_id():
    assert drive_id("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view") == "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    assert drive_id("https://docs.google.com/viewer?url=https://x.com/a.pdf") is None


def test_file_kind():
    assert file_kind(b"%PDF-1.7 ...") == "pdf"
    assert file_kind(b"<!DOCTYPE html><html>") == "html"


# ---------- whole pipeline ----------
def test_esign_pdf_needs_no_vision_call(monkeypatch):
    monkeypatch.setattr(pipeline, "call_vision", lambda *a, **k: pytest.fail("vision should not be called"))
    f = next(SAMPLES.glob("Green Meadows*.pdf"))
    r = audit_document(f.read_bytes(), f.name)
    assert (r.society_name, r.is_stamped, r.is_signed) == ("Green Meadows CHSL", "Yes", "Yes")


def test_vision_only_asked_open_questions(monkeypatch):
    prompts = []
    def fake(b64, prompt, *a, **k):
        prompts.append(prompt)
        return '{"is_stamped": "No", "is_signed": "Yes"}'
    monkeypatch.setattr(pipeline, "call_vision", fake)
    f = SAMPLES / "Lakeview Apartments.pdf"
    r = audit_document(f.read_bytes(), f.name)
    assert r.society_name == "Lakeview Apartment Owners Association"     # found in the table, for free
    assert "society_name" not in prompts[0]                               # so the model was not asked for it
    assert (r.is_stamped, r.is_signed) == ("No", "Yes")


def test_blank_template_is_not_given_a_guessed_name(monkeypatch):
    monkeypatch.setattr(pipeline, "call_vision", lambda *a, **k: "I am not sure.")
    f = SAMPLES / "blank_template.pdf"
    r = audit_document(f.read_bytes(), f.name)
    assert r.society_name == "Not listed"
    assert r.is_stamped == "Review" and r.is_signed == "Review"            # no answer -> human review, not "No"
