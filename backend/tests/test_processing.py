from docx import Document as DocxDocument
import pymupdf
from app.services.documents import chunk_pages, extract_pages


def test_chunking_preserves_content_and_page_numbers():
    text = "word " * 550
    chunks = chunk_pages([(4, text)], size=250, overlap=30)
    assert len(chunks) > 1
    assert all(c["page_number"] == 4 for c in chunks)
    assert all(len(c["text"]) <= 250 for c in chunks)


def test_empty_text_has_no_chunks():
    assert chunk_pages([(None, "   ")]) == []


def test_pdf_extraction_preserves_page_number(tmp_path):
    path = tmp_path / "sample.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Quarterly revenue increased.")
    pdf.save(path)
    pdf.close()
    pages = extract_pages(path, ".pdf")
    assert pages[0][0] == 1
    assert "Quarterly revenue" in pages[0][1]


def test_docx_extraction(tmp_path):
    path = tmp_path / "sample.docx"
    doc = DocxDocument()
    doc.add_paragraph("Project delivery is planned for June.")
    doc.save(path)
    pages = extract_pages(path, ".docx")
    assert pages[0][0] is None
    assert "planned for June" in pages[0][1]
