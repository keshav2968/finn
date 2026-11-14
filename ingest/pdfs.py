"""Download filing PDFs (cached) and pull their text in Python.

Text extraction happens here, not in a model: only the pages we need are then sent
to an LLM. A PDF whose pages carry almost no text is a scan; callers can send those
bytes to a provider that reads PDFs (Gemini) instead.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from .common import get_logger
from .http import FetchError, NotFound, PoliteSession

log = get_logger("pdfs")

BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Accept": "application/pdf,*/*"}
SCANNED_PAGE_CHARS = 25  # a page with fewer non-space characters than this has no text layer


class PdfError(RuntimeError):
    pass


@dataclass
class PdfText:
    pages: list[str]
    page_count: int

    @property
    def scanned(self) -> bool:
        """Most pages carry (almost) no extractable text: an image scan."""
        if not self.pages:
            return True
        empty = sum(1 for p in self.pages if len("".join(p.split())) < SCANNED_PAGE_CHARS)
        return empty * 2 > len(self.pages)

    def text(self, pages: list[int] | None = None, max_chars: int | None = None) -> str:
        """Selected pages (0-based), each headed "--- page N ---", optionally cut to max_chars."""
        idx = range(len(self.pages)) if pages is None else [i for i in pages if 0 <= i < len(self.pages)]
        out = "\n\n".join(f"--- page {i + 1} ---\n{self.pages[i]}" for i in idx)
        return out if max_chars is None else out[:max_chars]


def pdf_cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.pdf"


def fetch_pdf(http: PoliteSession, url: str, cache_dir: Path, offline: bool = False) -> bytes:
    """PDF bytes for `url`, from the cache when present (filings never change)."""
    path = pdf_cache_path(cache_dir, url)
    if path.exists():
        return path.read_bytes()
    if offline:
        raise PdfError(f"--offline: no cached copy of {url}")
    try:
        resp = http.get(url, headers=BSE_HEADERS, accept=lambda r: r.content[:5] == b"%PDF-")
    except NotFound as exc:
        raise PdfError(f"404 for {url}") from exc
    except FetchError as exc:
        raise PdfError(f"could not download a PDF from {url}: {exc}") from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


def extract_text(data: bytes, max_pages: int | None = None, layout: bool = True) -> PdfText:
    """Text per page. layout=True keeps table columns aligned, which matters for results."""
    if data[:5] != b"%PDF-":
        raise PdfError("not a PDF")
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            texts = []
            for page in pages:
                text = page.extract_text(layout=layout) or ""
                texts.append(re.sub(r"[ \t]+\n", "\n", text))
            return PdfText(texts, len(pdf.pages))
    except PdfError:
        raise
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many types on broken files
        raise PdfError(f"could not read PDF: {type(exc).__name__}: {exc}") from exc
