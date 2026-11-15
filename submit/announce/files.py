"""The PDF moves at announce (CONTRACT.md, Files).

    current version   ftp/arxiv/papers/YYMM/ID.pdf     key_patterns.current_pdf_path
    earlier versions  orig/arxiv/papers/YYMM/IDvN.pdf  key_patterns.previous_pdf_path

Order for version N of ID, chosen so that a re-run after a crash at any point is safe:
1. if N > 1 and version N-1 had a PDF: write orig/...v(N-1) unless it is already there,
   copying from version N-1's own staged upload (never from ftp/, which a crashed run
   may already have overwritten);
2. a new version or replacement: copy the staged PDF to ftp/; a withdrawal: delete ftp/.
All writes are whole-object, so re-running the steps gives the same result.
`undo` restores ftp/ if the database commit then fails.
"""
from dataclasses import dataclass
from typing import Optional

from arxiv.files.key_patterns import current_pdf_path, previous_pdf_path
from arxiv.identifier import Identifier

from ..storage import Store


@dataclass(frozen=True)
class FilePlan:
    current_key: str                  # ftp/... for this paper
    new_pdf: Optional[str]            # staged key to publish; None for a withdrawal
    prev_orig_key: Optional[str]      # orig/... for version N-1, if it had a PDF
    prev_source: Optional[str]        # where version N-1's PDF can be read


def plan(paper_id: str, version: int, new_pdf: Optional[str], prev_had_pdf: bool,
         prev_staged: Optional[str]) -> FilePlan:
    current = current_pdf_path(Identifier(paper_id))
    if version > 1 and prev_had_pdf:
        orig = previous_pdf_path(Identifier(f"{paper_id}v{version - 1}"))
        return FilePlan(current, new_pdf, orig, prev_staged or current)
    return FilePlan(current, new_pdf, None, None)


def publish(store: Store, fp: FilePlan) -> None:
    if fp.prev_orig_key and not store.exists(fp.prev_orig_key):
        if not store.exists(fp.prev_source):  # type: ignore[arg-type]
            raise FileNotFoundError(f"previous version's PDF not found at {fp.prev_source}")
        store.copy(fp.prev_source, fp.prev_orig_key)  # type: ignore[arg-type]
    if fp.new_pdf:
        if not store.exists(fp.new_pdf):
            raise FileNotFoundError(f"staged PDF not found at {fp.new_pdf}")
        store.copy(fp.new_pdf, fp.current_key)
    else:
        store.delete(fp.current_key)


def undo(store: Store, fp: FilePlan) -> None:
    """Put ftp/ back as it was before `publish` (the old current PDF, or none)."""
    if fp.prev_orig_key and store.exists(fp.prev_orig_key):
        store.copy(fp.prev_orig_key, fp.current_key)
    else:
        store.delete(fp.current_key)
