import pytest
from pdf_maker import make_pdf

from ingest.pdfs import PdfError, extract_text, fetch_pdf, pdf_cache_path


def test_extracts_text_per_page_and_selects_pages():
    data = make_pdf([["Statement of unaudited results", "Revenue from operations 49,244"], ["Notes to the results"]])
    text = extract_text(data)
    assert text.page_count == 2 and not text.scanned
    assert "Revenue from operations 49,244" in text.pages[0]
    picked = text.text(pages=[1])
    assert picked.startswith("--- page 2 ---") and "Notes" in picked and "Revenue" not in picked
    assert len(text.text(max_chars=20)) == 20
    assert extract_text(data, max_pages=1).pages == text.pages[:1]


def test_blank_pages_count_as_a_scan():
    assert extract_text(make_pdf([[""], [""]])).scanned


def test_rejects_non_pdfs():
    with pytest.raises(PdfError):
        extract_text(b"<html>error page</html>")
    with pytest.raises(PdfError):
        extract_text(b"%PDF-1.4 truncated garbage")


def test_fetch_uses_the_cache_and_offline_never_downloads(tmp_path):
    url = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=x.pdf"
    path = pdf_cache_path(tmp_path, url)
    path.write_bytes(b"%PDF-cached")

    class NoNetwork:
        def get(self, *a, **k):
            raise AssertionError("network used")

    assert fetch_pdf(NoNetwork(), url, tmp_path) == b"%PDF-cached"
    with pytest.raises(PdfError):
        fetch_pdf(NoNetwork(), url + "2", tmp_path, offline=True)
