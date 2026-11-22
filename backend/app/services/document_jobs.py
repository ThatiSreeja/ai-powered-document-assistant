import logging
from datetime import timedelta
from pathlib import Path
from threading import Thread
from time import perf_counter, sleep
from uuid import uuid4

from flask import current_app
from sqlalchemy import and_, delete, or_, select, update

from app.extensions import db
from app.models import Document, DocumentChunk, DocumentFile, ProcessingLog, utcnow
from app.services.documents import chunk_pages, extract_pages
from app.services.vectors import delete_document, embed_chunks, store_chunks

PROCESSING = ("extracting", "embedding", "indexing")


def enqueue(document):
    document.status = "uploaded"
    document.error_message = None
    document.job_token = None
    document.job_attempts = 0


def has_stored_file(document_id):
    return db.session.scalar(select(DocumentFile.document_id).where(
        DocumentFile.document_id == document_id)) is not None


def file_source(document):
    stored = db.session.get(DocumentFile, document.id)
    if stored is not None:
        return stored.data
    path = Path(current_app.config["UPLOAD_FOLDER"]) / document.stored_name
    return path if path.is_file() else None


def _owned_job(document_id, token):
    return db.session.scalar(select(Document).where(
        Document.id == document_id, Document.job_token == token,
    ).with_for_update())


def _advance(document_id, token, status):
    document = _owned_job(document_id, token)
    if document is None:
        db.session.rollback()
        return False
    document.status = status
    document.updated_at = utcnow()
    db.session.commit()
    return True


def _cleanup(document_id, token):
    document = _owned_job(document_id, token)
    if document is None:
        return
    path = Path(current_app.config["UPLOAD_FOLDER"]) / document.stored_name
    legacy_index = Path(current_app.config["CHROMA_PATH"]) / "chroma.sqlite3"
    if legacy_index.is_file():
        delete_document(document_id)
    path.unlink(missing_ok=True)
    # Explicit deletion also works with local SQLite setups where FK cascades are disabled.
    db.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    db.session.execute(delete(DocumentFile).where(DocumentFile.document_id == document_id))
    db.session.execute(delete(ProcessingLog).where(ProcessingLog.document_id == document_id))
    db.session.delete(document)
    db.session.commit()


def _process(document_id, token):
    document = db.session.get(Document, document_id)
    source, extension = file_source(document), "." + document.file_type
    db.session.rollback()
    if source is None:
        raise ValueError("The original file is unavailable. Upload it again.")
    started = perf_counter()
    legacy = isinstance(source, Path)
    if legacy:
        source = source.read_bytes()
    chunks = chunk_pages(extract_pages(source, extension))
    extracted = perf_counter()
    if not chunks:
        raise ValueError("No readable text was found in this file.")
    if not _advance(document_id, token, "embedding"):
        return
    vectors = embed_chunks(chunks)
    embedded = perf_counter()
    if not _advance(document_id, token, "indexing"):
        return
    document = _owned_job(document_id, token)
    if document is None:
        return
    if legacy and not has_stored_file(document_id):
        db.session.add(DocumentFile(document_id=document_id, data=source))
    store_chunks(document_id, chunks, vectors)
    document.status = "ready"
    document.job_token = None
    document.error_message = None
    db.session.add(ProcessingLog(document_id=document_id, stage="ingestion",
                                 status="success", message=f"Indexed {len(chunks)} chunks"))
    db.session.commit()
    current_app.logger.info(
        "Document job %s extraction=%.3fs embedding=%.3fs indexing=%.3fs chunks=%s",
        document_id, extracted - started, embedded - extracted, perf_counter() - embedded, len(chunks),
    )


def process_next():
    now = utcnow()
    claimable = or_(
        Document.status == "uploaded",
        and_(Document.status.in_(PROCESSING), Document.updated_at < now - timedelta(minutes=5)),
        and_(Document.status == "deleting", or_(
            Document.job_token.is_(None), Document.updated_at < now - timedelta(minutes=5),
        )),
    )
    document = db.session.scalar(select(Document).where(claimable)
                                 .order_by(Document.updated_at, Document.id).limit(1)
                                 .with_for_update(skip_locked=True))
    if document is None:
        db.session.rollback()
        return False
    document_id, token = document.id, str(uuid4())
    deleting = document.status == "deleting"
    claimed = db.session.execute(update(Document).where(
        Document.id == document_id, claimable,
    ).execution_options(synchronize_session=False).values(
        job_attempts=Document.job_attempts + 1, job_token=token,
        status="deleting" if deleting else "extracting", updated_at=now,
    ))
    db.session.commit()
    if not claimed.rowcount:
        return False
    started = perf_counter()
    try:
        if deleting:
            _cleanup(document_id, token)
            current_app.logger.info("Document cleanup %s duration=%.3fs", document_id, perf_counter() - started)
        else:
            _process(document_id, token)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Document job %s failed (%s)", document_id, type(exc).__name__)
        document = _owned_job(document_id, token)
        if document is not None:
            document.updated_at = utcnow()
            if not deleting:
                document.job_token = None
                document.status = "uploaded" if isinstance(exc, RuntimeError) and document.job_attempts < 2 else "failed"
                document.error_message = str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError)) else (
                    "Processing failed. Retry this document.")
            db.session.commit()
    return True


def start_document_workers(app):
    app.logger.setLevel(logging.INFO)

    def run():
        while True:
            try:
                with app.app_context():
                    if process_next():
                        continue
            except Exception as exc:
                app.logger.warning("Document worker unavailable (%s)", type(exc).__name__)
            sleep(1)

    for index in range(app.config["DOCUMENT_WORKERS"]):
        Thread(target=run, name=f"document-worker-{index}", daemon=True).start()
