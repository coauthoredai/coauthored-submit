"""Between HTML form fields and the pydantic models.

Author rows are numbered fields (`author-3-display_name`, ...); blank rows are skipped,
and the form is re-rendered with the remaining rows numbered 1..n. Errors come back keyed
by the HTML id of the field they belong to in that re-rendered form, so templates can tie
each message to its field with aria-describedby.
"""
from typing import Any, Mapping, Optional

from pydantic import ValidationError
from werkzeug.datastructures import MultiDict

from ..licenses import DEFAULT_LICENSE
from .schema import SubmissionIn

AUTHOR_FIELDS = ("display_name", "kind", "contribution", "orcid", "ai_system", "ai_version",
                 "ai_provider")
TEXT_AUTHOR_FIELDS = ("display_name", "contribution", "orcid", "ai_system", "ai_version",
                      "ai_provider")
DECLARATIONS = ("responsibility", "ai_accurate", "coauthors_agreed", "license_right")
MAX_ROWS = 100


def author_id(row: int, field: str) -> str:
    return f"author-{row}-{field}"


def read_authors(form: MultiDict) -> list[dict[str, Any]]:
    """Author dicts in row order. A row with no text in it is skipped."""
    try:
        rows = min(int(form.get("author_rows", "0")), MAX_ROWS)
    except ValueError:
        rows = 0
    submitter_row = form.get("submitter", "")
    authors = []
    for row in range(1, rows + 1):
        values = {f: form.get(author_id(row, f), "") for f in AUTHOR_FIELDS}
        if not any(values[f].strip() for f in TEXT_AUTHOR_FIELDS):
            continue
        values["kind"] = values["kind"] if values["kind"] in ("human", "ai") else "human"
        values["is_responsible"] = form.get(author_id(row, "is_responsible")) == "on"
        values["is_submitter"] = submitter_row == str(row)
        authors.append(values)
    return authors


def read_submission(form: MultiDict) -> dict[str, Any]:
    authors = read_authors(form)
    return {
        "title": form.get("title", ""),
        "abstract": form.get("abstract", ""),
        "comments": form.get("comments", ""),
        "primary_category": form.get("primary_category", ""),
        "cross_lists": form.getlist("cross_lists"),
        "license": form.get("license", DEFAULT_LICENSE),
        "authors": authors,
        "declarations": {d: form.get(f"declare_{d}") == "on" for d in DECLARATIONS},
    }


def _message(err: Mapping[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    if kind == "string_too_long":
        return f"Use at most {ctx.get('max_length')} characters."
    if kind == "too_long":
        return f"Use at most {ctx.get('max_length')} entries."
    if kind in ("too_short", "missing") and err["loc"][:1] == ("authors",):
        return "Add at least one author."
    if kind == "literal_error":
        return "Choose one of the options."
    return str(err.get("msg", "Check this field.")).removeprefix("Value error, ")


def field_errors(exc: ValidationError) -> dict[str, str]:
    """{html field id: message}. `authors` holds the author-list-wide message."""
    out: dict[str, str] = {}
    for err in exc.errors():
        loc = err["loc"]
        if loc[0] == "authors" and len(loc) >= 3 and isinstance(loc[1], int):
            key = author_id(loc[1] + 1, str(loc[2]))
        elif loc[0] == "declarations" and len(loc) >= 2:
            key = f"declare_{loc[1]}"
        elif loc[0] == "authors":
            key = "authors"
        else:
            key = str(loc[0])
        out.setdefault(key, _message(err))
    return out


def validate_submission(form: MultiDict, context: Mapping[str, Any]
                        ) -> tuple[Optional[SubmissionIn], dict[str, str], dict[str, Any]]:
    """(model or None, errors, raw values for re-rendering the form)."""
    data = read_submission(form)
    try:
        return SubmissionIn.model_validate(data, context=dict(context)), {}, data
    except ValidationError as exc:
        return None, field_errors(exc), data


def form_values_from(sub: Any) -> dict[str, Any]:
    """Pre-fill values from an existing submission (for edits and replacements)."""
    return {
        "title": sub.title, "abstract": sub.abstract, "comments": sub.comments or "",
        "primary_category": sub.primary_category,
        "cross_lists": [c for c in sub.cross_categories.split() if c],
        "license": sub.license,
        "authors": [{
            "display_name": c.display_name, "kind": c.kind, "contribution": c.contribution,
            "orcid": c.orcid or "", "ai_system": c.ai_system or "", "ai_version": c.ai_version or "",
            "ai_provider": c.ai_provider or "", "is_responsible": c.is_responsible,
            "is_submitter": c.is_submitter} for c in sub.contributors],
        "declarations": {d: False for d in DECLARATIONS},
    }


def blank_values(display_name: str = "") -> dict[str, Any]:
    return {
        "title": "", "abstract": "", "comments": "", "primary_category": "", "cross_lists": [],
        "license": DEFAULT_LICENSE,
        "authors": [{"display_name": display_name, "kind": "human", "contribution": "",
                     "orcid": "", "ai_system": "", "ai_version": "", "ai_provider": "",
                     "is_responsible": True, "is_submitter": True}],
        "declarations": {d: False for d in DECLARATIONS},
    }
