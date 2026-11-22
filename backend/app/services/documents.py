import re
from pathlib import Path
import pymupdf
from docx import Document as DocxDocument
from flask import current_app, has_app_context


def extract_pages(path, extension):
    if extension == ".pdf":
        config = current_app.config if has_app_context() else {}
        page_limit = config.get("MAX_PDF_PAGES", 1000)
        char_limit = config.get("MAX_EXTRACTED_CHARACTERS", 2000000)
        try:
            with pymupdf.open(path) as pdf:
                if not pdf.is_pdf or pdf.is_repaired:
                    raise ValueError("The file is damaged or is not a valid PDF.")
                if pdf.needs_pass:
                    raise ValueError("Unlock the password-protected PDF before uploading it.")
                if pdf.page_count > page_limit:
                    raise ValueError(f"The PDF exceeds the {page_limit}-page limit.")
                pages, length = [], 0
                for i, page in enumerate(pdf, 1):
                    text = page.get_text("text")
                    length += len(text)
                    if length > char_limit:
                        raise ValueError("The PDF contains too much text. Split it into smaller files.")
                    pages.append((i, text))
                return pages
        except pymupdf.FileDataError:
            raise ValueError("The file is damaged or is not a valid PDF.") from None
    if extension == ".docx":
        doc = DocxDocument(path)
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [(None, text)]
    return [(None, Path(path).read_text(encoding="utf-8", errors="replace"))]


def chunk_pages(pages, size=1000, overlap=150):
    chunks = []
    for page_number, raw in pages:
        text = re.sub(r"\s+", " ", raw).strip()
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start, end)
                if boundary > start + size // 2:
                    end = boundary
            value = text[start:end].strip()
            if value:
                chunks.append({"text": value, "page_number": page_number})
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks
