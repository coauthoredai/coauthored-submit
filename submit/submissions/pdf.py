"""Uploaded PDFs: type and size checks, hashing, and the staging key.

A PDF must start with `%PDF-` and be at most PDF_MAX_BYTES (50 MB policy maximum).
Staged PDFs live at `staging/<submission_id>/<sha256>.pdf` and are never served publicly.
"""
import hashlib
import tempfile
from dataclasses import dataclass
from typing import BinaryIO, IO

MAGIC = b"%PDF-"
CHUNK = 1024 * 1024


class PdfError(ValueError):
    pass


@dataclass
class CheckedPdf:
    file: IO[bytes]   # positioned at 0
    size: int
    sha256: str


def check_pdf(stream: BinaryIO | None, max_bytes: int) -> CheckedPdf:
    """Copy the upload to a temporary file while checking it. Raises PdfError."""
    if stream is None:
        raise PdfError("Choose a PDF file to upload.")
    head = stream.read(len(MAGIC))
    if not head:
        raise PdfError("Choose a PDF file to upload.")
    if head != MAGIC:
        raise PdfError("The file is not a PDF (it must start with %PDF-).")
    digest = hashlib.sha256(head)
    out = tempfile.SpooledTemporaryFile(max_size=8 * CHUNK)
    out.write(head)
    size = len(head)
    while chunk := stream.read(CHUNK):
        size += len(chunk)
        if size > max_bytes:
            out.close()
            raise PdfError(f"The PDF is larger than {max_bytes // (1024 * 1024)} MB.")
        digest.update(chunk)
        out.write(chunk)
    out.seek(0)
    return CheckedPdf(file=out, size=size, sha256=digest.hexdigest())


def staging_key(submission_id: int, sha256: str) -> str:
    return f"staging/{submission_id}/{sha256}.pdf"
