"""Validation rules for submissions (pydantic).

Author rules (Coauthored policy):
- at least one author is human, and at least one human author takes responsibility
  (`is_responsible`); an AI-only author list is refused;
- every author states a contribution;
- every AI author names its system, version and provider, and cannot hold an ORCID,
  take responsibility, or be the submitter;
- the submitter is one of the human authors: exactly one human author is marked
  "this is me" (`is_submitter`). Coauthored does not accept proxy submissions.

Context passed to `model_validate(..., context=...)`: `license_host`, `max_cross_lists`.
"""
import re
from typing import Annotated, Any, Literal, Optional

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field,
                      ValidationInfo, field_validator)
from pydantic_core import PydanticCustomError

from ..licenses import DEFAULT_LICENSE, offered_uris
from ..taxonomy import is_offered

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _clean(value: Any) -> Any:
    """Strip, collapse internal whitespace; empty strings become None."""
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


def _clean_text(value: Any) -> Any:
    """Like _clean but keeps paragraph breaks (abstracts, contributions)."""
    if isinstance(value, str):
        value = "\n".join(" ".join(line.split()) for line in value.replace("\r\n", "\n").split("\n"))
        value = re.sub(r"\n{3,}", "\n\n", value).strip()
        return value or None
    return value


def orcid_checksum_ok(orcid: str) -> bool:
    """ISO 7064 11,2 check digit, as ORCID uses."""
    digits = orcid.replace("-", "")
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def _orcid(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.upper().removeprefix("HTTPS://ORCID.ORG/").removeprefix("HTTP://ORCID.ORG/")
    if not ORCID_RE.match(value) or not orcid_checksum_ok(value):
        raise PydanticCustomError("orcid", "Enter an ORCID iD like 0000-0002-1825-0097.")
    return value


Line = Annotated[Optional[str], BeforeValidator(_clean)]
Text = Annotated[Optional[str], BeforeValidator(_clean_text)]


def _required(value: Optional[str], what: str) -> str:
    if not value:
        raise PydanticCustomError("required", f"Enter {what}.")
    return value


class AuthorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["human", "ai"]
    display_name: Annotated[Line, AfterValidator(lambda v: _required(v, "the author's name"))] = Field(
        default=None, max_length=255, validate_default=True)
    contribution: Annotated[Text, AfterValidator(lambda v: _required(v, "this author's contribution"))] = Field(
        default=None, max_length=2000, validate_default=True)
    orcid: Line = Field(default=None, validate_default=True)
    is_responsible: bool = Field(default=False, validate_default=True)
    is_submitter: bool = Field(default=False, validate_default=True)
    ai_system: Line = Field(default=None, max_length=128, validate_default=True)
    ai_version: Line = Field(default=None, max_length=128, validate_default=True)
    ai_provider: Line = Field(default=None, max_length=128, validate_default=True)

    @field_validator("orcid")
    @classmethod
    def _check_orcid(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        if info.data.get("kind") == "ai":
            if v:
                raise PydanticCustomError("ai_orcid", "AI authors do not have an ORCID iD.")
            return None
        return _orcid(v)

    @field_validator("is_responsible")
    @classmethod
    def _check_responsible(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("kind") == "ai":
            raise PydanticCustomError(
                "ai_responsible", "Only human authors can take responsibility for the paper.")
        return v

    @field_validator("is_submitter")
    @classmethod
    def _check_submitter(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("kind") == "ai":
            raise PydanticCustomError(
                "ai_submitter", "The submitter must be one of the human authors.")
        return v

    @field_validator("ai_system", "ai_version", "ai_provider")
    @classmethod
    def _check_ai_fields(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        if info.data.get("kind") != "ai":
            return None  # only meaningful for AI authors; ignored for humans
        if not v:
            what = {"ai_system": "the AI system (for example, Claude)",
                    "ai_version": "the model version (for example, Opus 5.5)",
                    "ai_provider": "the provider (for example, Anthropic)"}[info.field_name or ""]
            raise PydanticCustomError("required", f"Enter {what}.")
        return v


def _authors_rule(authors: list[AuthorIn]) -> list[AuthorIn]:
    humans = [a for a in authors if a.kind == "human"]
    if not humans:
        raise PydanticCustomError(
            "no_human", "At least one author must be a human who takes responsibility for "
                        "the paper. AI-only author lists are not accepted.")
    if not any(a.is_responsible for a in humans):
        raise PydanticCustomError(
            "no_responsible", "Tick 'takes responsibility' for at least one human author.")
    submitters = [a for a in authors if a.is_submitter]
    if len(submitters) != 1:
        raise PydanticCustomError(
            "submitter", "Mark which human author you are. The submitter must be one of the "
                         "human authors.")
    return authors


Authors = Annotated[list[AuthorIn], Field(min_length=1, max_length=100), AfterValidator(_authors_rule)]


def _true(what: str) -> Any:
    def check(v: bool) -> bool:
        if v is not True:
            raise PydanticCustomError("declaration", f"Confirm that {what}.")
        return v
    return AfterValidator(check)


class Declarations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    responsibility: Annotated[bool, _true("the human authors take responsibility for the paper")] = Field(
        default=False, validate_default=True)
    ai_accurate: Annotated[bool, _true("the AI contributions are stated accurately")] = Field(
        default=False, validate_default=True)
    coauthors_agreed: Annotated[bool, _true("all human co-authors agreed to this submission")] = Field(
        default=False, validate_default=True)
    license_right: Annotated[bool, _true("you have the right to distribute the paper under the chosen licence")] = Field(
        default=False, validate_default=True)


class SubmissionIn(BaseModel):
    """A new paper or a replacement: everything except the PDF."""
    model_config = ConfigDict(extra="forbid")

    title: Annotated[Line, AfterValidator(lambda v: _required(v, "a title"))] = Field(
        default=None, max_length=255, validate_default=True)
    abstract: Annotated[Text, AfterValidator(lambda v: _required(v, "an abstract"))] = Field(
        default=None, max_length=1920, validate_default=True)
    comments: Text = Field(default=None, max_length=1000)
    primary_category: Line = Field(default=None, validate_default=True)
    cross_lists: list[str] = Field(default_factory=list)
    license: str = DEFAULT_LICENSE
    authors: Authors
    declarations: Declarations

    @field_validator("authors", mode="before")
    @classmethod
    def _some_human(cls, v: Any) -> Any:
        # Checked before the individual authors, so an AI-only list is reported as such
        # even when its rows have errors of their own.
        if isinstance(v, list) and v and all(isinstance(a, dict) and a.get("kind") == "ai" for a in v):
            raise PydanticCustomError(
                "no_human", "At least one author must be a human who takes responsibility for "
                            "the paper. AI-only author lists are not accepted.")
        return v

    @field_validator("abstract")
    @classmethod
    def _abstract_length(cls, v: str) -> str:
        if len(v) < 20:
            raise PydanticCustomError("short", "The abstract is too short (20 characters at least).")
        return v

    @field_validator("primary_category")
    @classmethod
    def _primary(cls, v: Optional[str]) -> str:
        if not v:
            raise PydanticCustomError("required", "Choose a primary category.")
        if not is_offered(v):
            raise PydanticCustomError("category", "Choose a primary category from the list.")
        return v

    @field_validator("cross_lists")
    @classmethod
    def _crosses(cls, v: list[str], info: ValidationInfo) -> list[str]:
        crosses = [c.strip() for c in v if c and c.strip()]
        limit = int((info.context or {}).get("max_cross_lists", 4))
        if any(not is_offered(c) for c in crosses):
            raise PydanticCustomError("category", "Choose cross-list categories from the list.")
        primary = info.data.get("primary_category")
        crosses = [c for c in dict.fromkeys(crosses) if c != primary]
        if len(crosses) > limit:
            raise PydanticCustomError("too_many", f"Choose at most {limit} cross-list categories.")
        return crosses

    @field_validator("license")
    @classmethod
    def _license(cls, v: str, info: ValidationInfo) -> str:
        host = (info.context or {}).get("license_host", "aicoauthored.dev")
        if v not in offered_uris(host):
            raise PydanticCustomError("license", "Choose one of the licences offered.")
        return v


class WithdrawalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[Text, AfterValidator(lambda v: _required(v, "the reason for withdrawal"))] = Field(
        default=None, max_length=1000, validate_default=True)
    authorized: Annotated[bool, _true("you may withdraw this paper on behalf of its authors")] = Field(
        default=False, validate_default=True)


class ReasonIn(BaseModel):
    """A moderator's decision. The reason is required for reject and request_changes."""
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject", "request_changes", "hold"]
    reason: Text = Field(default=None, max_length=4000)
