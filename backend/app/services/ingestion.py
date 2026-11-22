import hashlib
from pathlib import Path
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models import Document, DocumentFile, ProcessingLog, User
from app.services.documents import chunk_pages, extract_pages
from app.services.vectors import add_document, delete_document
from app.services.document_jobs import enqueue, has_stored_file

MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def process_document(document, *, retry=False):
    path = Path(current_app.config["UPLOAD_FOLDER"]) / document.stored_name
    try:
        chunks = chunk_pages(extract_pages(path, "." + document.file_type))
        if not chunks:
            raise ValueError("No readable text was found in this file.")
        if retry:
            delete_document(document.id)
        add_document(document, chunks)
        document.status, document.error_message = "ready", None
        message = f"Indexed {len(chunks)} chunks"
    except Exception as exc:
        current_app.logger.warning("Could not index document %s (%s)", document.id, type(exc).__name__)
        document.status = "failed"
        message = str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError)) else "Processing failed. Please retry."
        document.error_message = message
    db.session.add(ProcessingLog(document_id=document.id, stage="ingestion",
                                 status="success" if document.status == "ready" else "failed", message=message))


def ingest(file, user_id, *, pdf_only=False):
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("The filename is invalid.")
    extension = Path(name).suffix.lower()
    if extension not in MIME or (pdf_only and extension != ".pdf"):
        raise ValueError("Only PDF files can be attached to chat." if pdf_only else "Only PDF, DOCX and TXT files are supported.")
    if file.mimetype not in {MIME[extension], "application/octet-stream", ""}:
        raise ValueError("The file content type does not match its extension.")
    if extension == ".pdf":
        header = file.stream.read(1024)
        file.stream.seek(0)
        if b"%PDF-" not in header:
            raise ValueError("The file is not a valid PDF.")

    checksum = hashlib.sha256()
    for block in iter(lambda: file.stream.read(1024 * 1024), b""):
        checksum.update(block)
    digest = checksum.hexdigest()
    file.stream.seek(0)
    # Serialize ingestion for this owner so duplicate requests reuse the completed document.
    User.query.filter_by(id=user_id).with_for_update().one()
    existing = Document.query.filter_by(user_id=user_id, content_hash=digest).with_for_update().first()
    if existing and existing.file_type != extension[1:]:
        raise ValueError("These bytes were previously uploaded with a different file type.")
    if current_app.config["DOCUMENT_JOBS"]:
        if existing and existing.status == "deleting":
            raise ValueError("This document is being deleted. Retry the upload in a moment.")
        document = existing or Document(
            user_id=user_id, original_name=name[:255], stored_name=f"{user_id}/{uuid4().hex}{extension}",
            file_type=extension[1:], content_hash=digest, file_size=0,
        )
        if existing and has_stored_file(existing.id):
            if existing.status == "failed":
                enqueue(existing)
            return existing
        if existing and existing.status == "ready":
            root = Path(current_app.config["UPLOAD_FOLDER"])
            if (root / existing.stored_name).is_file() and (
                Path(current_app.config["CHROMA_PATH"]) / "chroma.sqlite3"
            ).is_file():
                return existing
        data = file.stream.read()
        document.file_size = len(data)
        enqueue(document)
        db.session.add(document)
        db.session.flush()
        db.session.add(DocumentFile(document_id=document.id, data=data))
        return document
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    if existing:
        path = upload_root / existing.stored_name
        if path.is_file() and existing.status == "ready":
            return existing
        if not path.is_file():
            save_upload(file, path)
        process_document(existing, retry=True)
        return existing

    stored = f"{uuid4().hex}{extension}"
    path = upload_root / str(user_id) / stored
    size = save_upload(file, path)
    document = Document(user_id=user_id, original_name=name[:255], stored_name=f"{user_id}/{stored}",
                        file_type=extension[1:], file_size=size, content_hash=digest, status="processing")
    db.session.add(document)
    db.session.flush()
    process_document(document)
    return document


def save_upload(file, path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file.save(path)
        return path.stat().st_size
    except OSError:
        path.unlink(missing_ok=True)
        raise ValueError("The server could not store this file. Please retry.") from None
