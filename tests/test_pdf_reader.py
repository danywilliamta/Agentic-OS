"""Unit tests for agent_harness.tools.pdf_reader.read_pdf."""

import sys
from types import SimpleNamespace

import PyPDF2

from agent_harness.tools.pdf_reader import read_pdf


class TestReadPdf:
    def test_txt_file_is_read_directly(self, tmp_path):
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("hello world", encoding="utf-8")

        result = read_pdf(str(txt_path))

        assert result == {
            "success": True,
            "content": "hello world",
            "pages": 1,
            "file_path": str(txt_path),
            "error": None,
        }

    def test_missing_txt_file_returns_file_not_found_error(self, tmp_path):
        missing_path = tmp_path / "does-not-exist.txt"

        result = read_pdf(str(missing_path))

        assert result["success"] is False
        assert result["content"] is None
        assert "File not found" in result["error"]

    def test_real_pdf_is_extracted_via_pypdf2(self, tmp_path):
        pdf_path = tmp_path / "doc.pdf"
        writer = PyPDF2.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = read_pdf(str(pdf_path))

        assert result["success"] is True
        assert result["pages"] == 2
        assert result["error"] is None

    def test_pypdf2_unavailable_falls_back_to_pdfplumber(self, tmp_path, monkeypatch):
        class FakePage:
            def extract_text(self):
                return "hello from pdfplumber"

        class FakePdfplumberPdf:
            def __init__(self):
                self.pages = [FakePage(), FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setitem(sys.modules, "PyPDF2", None)
        monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda path: FakePdfplumberPdf()))

        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"irrelevant, pdfplumber.open is mocked")

        result = read_pdf(str(pdf_path))

        assert result["success"] is True
        assert result["pages"] == 2
        assert "hello from pdfplumber" in result["content"]

    def test_corrupt_pdf_is_caught_as_error(self, tmp_path):
        pdf_path = tmp_path / "corrupt.pdf"
        pdf_path.write_bytes(b"this is not a real pdf")

        result = read_pdf(str(pdf_path))

        assert result["success"] is False
        assert result["content"] is None
        assert "Error reading PDF" in result["error"]
