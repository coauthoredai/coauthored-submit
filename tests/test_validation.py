"""Validation rules for submissions."""
import io

import pytest
from pydantic import ValidationError
from werkzeug.datastructures import MultiDict

from submit.submissions.forms import validate_submission
from submit.submissions.pdf import PdfError, check_pdf, staging_key
from submit.submissions.schema import SubmissionIn, WithdrawalIn, orcid_checksum_ok
from tests.helpers import author_dicts, form_fields, submission_dict, submission_in

CTX = {"max_cross_lists": 4, "license_host": "aicoauthored.dev"}


def errors(**overrides):
    with pytest.raises(ValidationError) as info:
        SubmissionIn.model_validate(submission_dict(**overrides), context=CTX)
    return {tuple(e["loc"]): e["msg"] for e in info.value.errors()}


def test_valid_submission_passes_and_is_normalised():
    data = submission_in(title="  On   games ", cross_lists=["math.CO", "cs.GT", "math.CO", ""])
    assert data.title == "On games"
    assert data.cross_lists == ["math.CO"]  # primary and duplicates dropped
    assert [a.kind for a in data.authors] == ["human", "ai"]


def test_ai_only_author_list_is_rejected():
    ai = author_dicts()[1]
    errs = errors(authors=[ai, dict(ai, display_name="Gemini")])
    assert "AI-only author lists are not accepted" in errs[("authors",)]


def test_a_human_must_take_responsibility():
    human, ai = author_dicts()
    errs = errors(authors=[dict(human, is_responsible=False), ai])
    assert "responsibility" in errs[("authors",)]


@pytest.mark.parametrize("field", ["ai_system", "ai_version", "ai_provider", "contribution"])
def test_every_ai_author_needs_system_version_provider_and_contribution(field):
    human, ai = author_dicts()
    errs = errors(authors=[human, dict(ai, **{field: "  "})])
    assert ("authors", 1, field) in errs


def test_every_human_author_needs_a_contribution():
    human, ai = author_dicts()
    assert ("authors", 0, "contribution") in errors(authors=[dict(human, contribution=""), ai])


def test_ai_cannot_take_responsibility_or_hold_an_orcid():
    human, ai = author_dicts()
    errs = errors(authors=[human, dict(ai, is_responsible=True, orcid="0000-0002-1825-0097")])
    assert ("authors", 1, "is_responsible") in errs
    assert ("authors", 1, "orcid") in errs


def test_submitter_must_be_one_of_the_human_authors():
    human, ai = author_dicts()
    assert "submitter" in errors(authors=[dict(human, is_submitter=False), ai])[("authors",)]
    assert ("authors", 1, "is_submitter") in errors(
        authors=[dict(human, is_submitter=False), dict(ai, is_submitter=True)])
    second = dict(human, display_name="Charles Babbage")
    assert "submitter" in errors(authors=[human, second, ai])[("authors",)]


def test_ai_fields_are_ignored_for_humans():
    human, ai = author_dicts()
    data = submission_in(authors=[dict(human, ai_system="leftover"), ai])
    assert data.authors[0].ai_system is None


def test_orcid_check_digit():
    assert orcid_checksum_ok("0000-0002-1825-0097")
    assert orcid_checksum_ok("0000-0002-9079-593X")
    assert not orcid_checksum_ok("0000-0002-1825-0098")
    human, ai = author_dicts()
    assert ("authors", 0, "orcid") in errors(authors=[dict(human, orcid="0000-0002-1825-0098"), ai])
    url_form = submission_in(authors=[dict(human, orcid="https://orcid.org/0000-0002-1825-0097"), ai])
    assert url_form.authors[0].orcid == "0000-0002-1825-0097"


def test_licence_must_be_offered():
    assert ("license",) in errors(license="http://arxiv.org/licenses/nonexclusive-distrib/1.0/")
    ok = submission_in(license="https://aicoauthored.dev/licenses/nonexclusive-distrib/1.0/")
    assert ok.license.startswith("https://aicoauthored.dev/")


def test_categories_must_be_active_canonical_and_limited():
    assert ("primary_category",) in errors(primary_category="cmp-lg")      # inactive
    assert ("primary_category",) in errors(primary_category="math.IT")     # alias of cs.IT
    assert ("primary_category",) in errors(primary_category="")
    assert ("cross_lists",) in errors(cross_lists=["not.real"])
    assert ("cross_lists",) in errors(cross_lists=["math.CO", "math.PR", "math.ST", "cs.LG", "cs.AI"])
    assert submission_in(primary_category="hep-th", cross_lists=[]).primary_category == "hep-th"


def test_declarations_are_all_required():
    errs = errors(declarations={"responsibility": True})
    assert {("declarations", "ai_accurate"), ("declarations", "coauthors_agreed"),
            ("declarations", "license_right")} <= set(errs)


def test_title_and_abstract_limits():
    assert ("title",) in errors(title="x" * 256)
    assert ("title",) in errors(title="   ")
    assert ("abstract",) in errors(abstract="too short")
    assert ("abstract",) in errors(abstract="x" * 1921)


def test_withdrawal_needs_reason_and_authority():
    with pytest.raises(ValidationError) as info:
        WithdrawalIn.model_validate({"reason": " ", "authorized": False})
    assert {e["loc"] for e in info.value.errors()} == {("reason",), ("authorized",)}


def test_form_parsing_skips_blank_rows_and_maps_errors_to_field_ids():
    fields = form_fields(**{"author-2-ai_provider": "", "author_rows": "4",
                            "author-3-display_name": "", "author-4-display_name": "Grace Hopper",
                            "author-4-kind": "human", "author-4-contribution": ""})
    form = MultiDict([(k, v) for k, vs in fields.items() for v in (vs if isinstance(vs, list) else [vs])])
    model, errs, values = validate_submission(form, CTX)
    assert model is None
    # Rows re-render as 1..n without the blank row 3, so Grace becomes row 3.
    assert set(errs) == {"author-2-ai_provider", "author-3-contribution"}
    assert [a["display_name"] for a in values["authors"]] == ["Ada Lovelace", "Claude", "Grace Hopper"]


def test_pdf_checks():
    pdf = check_pdf(io.BytesIO(b"%PDF-1.7\nhello"), 1000)
    assert pdf.size == 14 and len(pdf.sha256) == 64
    assert staging_key(7, pdf.sha256) == f"staging/7/{pdf.sha256}.pdf"
    with pytest.raises(PdfError, match="not a PDF"):
        check_pdf(io.BytesIO(b"<html>%PDF-"), 1000)
    with pytest.raises(PdfError, match="larger"):
        check_pdf(io.BytesIO(b"%PDF-" + b"x" * 2000), 1000)
    with pytest.raises(PdfError):
        check_pdf(io.BytesIO(b""), 1000)
