from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import perf_counter
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import (
    create_access_token, get_csrf_token, get_jwt, get_jwt_identity, jwt_required,
    set_access_cookies, unset_jwt_cookies,
)
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Conversation, Document, Message, RevokedToken, User, utcnow
from app.services.documents import extract_pages
from app.services.ingestion import ingest, process_document
from app.services.document_jobs import enqueue, file_source, PROCESSING
from app.services.rag import answer_question, summarize
from app.services.groq_chat import GroqError
from app.services.vectors import delete_document

api = Blueprint("api", __name__, url_prefix="/api")
MAX_ATTACHMENTS = 10


def error(message, status=400):
    return jsonify({"error": message}), status


@api.errorhandler(GroqError)
def groq_error(exc):
    db.session.rollback()
    return error(str(exc), exc.status)


def owned_document(document_id, user_id, *, lock=False):
    query = Document.query.filter_by(id=document_id, user_id=user_id).filter(Document.status != "deleting")
    return (query.with_for_update() if lock else query).first()


def auth_response(user, status=200):
    token = create_access_token(
        identity=str(user.id), additional_claims={"account_created_at": user.account_created_at()},
    )
    if request.headers.get("X-Paperwise-Session") == "cookie":
        response = jsonify({"user": user.to_dict(), "csrf_token": get_csrf_token(token)})
        set_access_cookies(response, token)
    else:
        response = jsonify({"user": user.to_dict(), "access_token": token})
    response.headers["Cache-Control"] = "no-store"
    return response, status


@api.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name, email, password = (data.get("name", "").strip(), data.get("email", "").strip().lower(), data.get("password", ""))
    if not name or len(name) > 120 or len(email) > 255 or "@" not in email or len(password) < 8:
        return error("Provide a name, valid email and password of at least 8 characters.")
    if User.query.filter_by(email=email).first():
        return error("An account with this email already exists.", 409)
    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if User.query.filter_by(email=email).first():
            return error("An account with this email already exists.", 409)
        raise
    return auth_response(user, 201)


@api.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=data.get("email", "").strip().lower()).first()
    if not user or not user.check_password(data.get("password", "")):
        return error("Email or password is incorrect.", 401)
    return auth_response(user)


@api.post("/auth/logout")
@jwt_required()
def logout():
    claims = get_jwt()
    RevokedToken.query.filter(RevokedToken.expires_at <= utcnow()).delete()
    db.session.add(RevokedToken(
        jti=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc),
    ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if db.session.get(RevokedToken, claims["jti"]) is None:
            raise
    response = jsonify({"message": "Logged out."})
    unset_jwt_cookies(response)
    return response


@api.get("/auth/me")
@jwt_required()
def me():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return error("User not found.", 404)
    profile = user.to_dict()
    if request.headers.get("X-Paperwise-Session") == "cookie":
        profile["csrf_token"] = get_jwt().get("csrf")
    response = jsonify(profile)
    response.headers["Cache-Control"] = "no-store"
    return response


@api.route("/documents", methods=["GET", "POST"])
@jwt_required()
def documents():
    user_id = int(get_jwt_identity())
    if request.method == "GET":
        query = Document.query.filter_by(user_id=user_id).filter(Document.status != "deleting")
        search = request.args.get("q", "").strip()
        kind, status = request.args.get("type"), request.args.get("status")
        if search:
            query = query.filter(Document.original_name.ilike(f"%{search}%"))
        if kind:
            query = query.filter_by(file_type=kind.lower().lstrip("."))
        if status:
            query = query.filter_by(status=status)
        return jsonify([d.to_dict() for d in query.order_by(Document.created_at.desc()).all()])
    return upload_documents(user_id)


def owned_conversation(conversation_id, user_id, *, lock=False):
    query = Conversation.query.filter_by(id=conversation_id, user_id=user_id)
    return (query.with_for_update() if lock else query).first()


def upload_documents(user_id, conversation_id=None):
    started = perf_counter()
    files = request.files.getlist("files")
    if not files or len(files) > MAX_ATTACHMENTS:
        return error(f"Select between 1 and {MAX_ATTACHMENTS} files.")
    results = []
    for file in files:
        conversation = None
        if conversation_id is not None:
            conversation = owned_conversation(conversation_id, user_id, lock=True)
            if not conversation:
                return error("Conversation not found.", 404)
            if len(conversation.documents) >= MAX_ATTACHMENTS:
                results.append({"name": file.filename, "error": "This conversation already has 10 attachments."})
                db.session.rollback()
                continue
        try:
            doc = ingest(file, user_id, pdf_only=conversation is not None)
        except ValueError as exc:
            results.append({"name": file.filename, "error": str(exc)})
            db.session.rollback()
            continue
        if conversation is not None and doc not in conversation.documents:
            conversation.documents.append(doc)
            conversation.updated_at = utcnow()
        result = doc.to_dict()
        db.session.commit()
        results.append(result)
    if current_app.config["DOCUMENT_JOBS"]:
        current_app.logger.info("Document upload accepted files=%s duration=%.3fs", len(results), perf_counter() - started)
    return jsonify(results), 201


@api.get("/documents/<int:document_id>")
@jwt_required()
def get_document(document_id):
    doc = owned_document(document_id, int(get_jwt_identity()))
    return jsonify(doc.to_dict()) if doc else error("Document not found.", 404)


@api.get("/documents/<int:document_id>/pdf")
@jwt_required()
def view_pdf(document_id):
    doc = owned_document(document_id, int(get_jwt_identity()))
    if not doc or doc.file_type != "pdf" or doc.status != "ready":
        return error("PDF not found.", 404)
    source = file_source(doc)
    if source is None:
        return error("PDF file is unavailable.", 404)
    response = send_file(BytesIO(source) if isinstance(source, bytes) else source,
                         mimetype="application/pdf", download_name=doc.original_name)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@api.delete("/documents/<int:document_id>")
@jwt_required()
def remove_document(document_id):
    if current_app.config["DOCUMENT_JOBS"]:
        doc = Document.query.filter_by(id=document_id).with_for_update().first()
        if doc is None:
            return "", 204
        if doc.user_id != int(get_jwt_identity()):
            return error("Document not found.", 404)
        if doc.status != "deleting":
            doc.status = "deleting"
            doc.job_token = None
            doc.job_attempts = 0
            db.session.commit()
        return jsonify({"message": "Document removed. Cleanup queued."}), 202
    doc = owned_document(document_id, int(get_jwt_identity()), lock=True)
    if not doc:
        return error("Document not found.", 404)
    try:
        delete_document(doc.id)
    except Exception:
        current_app.logger.exception("Vector deletion failed for document %s", doc.id)
        return error("Could not delete document embeddings. Please retry.", 503)
    path = Path(current_app.config["UPLOAD_FOLDER"]) / doc.stored_name
    path.unlink(missing_ok=True)
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"message": "Document deleted."})


@api.post("/documents/<int:document_id>/reprocess")
@jwt_required()
def reprocess_document(document_id):
    doc = owned_document(document_id, int(get_jwt_identity()), lock=True)
    if not doc:
        return error("Document not found.", 404)
    if current_app.config["DOCUMENT_JOBS"]:
        if doc.status not in ("uploaded", *PROCESSING):
            if file_source(doc) is None:
                return error("The original file is unavailable. Upload it again.", 409)
            enqueue(doc)
            db.session.commit()
        return jsonify(doc.to_dict()), 202
    process_document(doc, retry=True)
    db.session.commit()
    return jsonify(doc.to_dict())


@api.route("/chat/conversations", methods=["GET", "POST"])
@jwt_required()
def conversations():
    uid = int(get_jwt_identity())
    if request.method == "GET":
        return jsonify([c.to_dict() for c in Conversation.query.filter_by(user_id=uid).order_by(Conversation.updated_at.desc()).all()])
    data = request.get_json(silent=True) or {}
    conv = Conversation(user_id=uid, title=(data.get("title") or "New conversation")[:255])
    db.session.add(conv)
    db.session.commit()
    return jsonify(conv.to_dict()), 201


@api.get("/chat/conversations/<int:conversation_id>")
@jwt_required()
def get_conversation(conversation_id):
    conv = Conversation.query.filter_by(id=conversation_id, user_id=int(get_jwt_identity())).first()
    if not conv:
        return error("Conversation not found.", 404)
    return jsonify({**conv.to_dict(True), "attachments": [doc.to_dict() for doc in conv.documents
                    if doc.user_id == conv.user_id and doc.status != "deleting"]})


@api.get("/chat/conversations/<int:conversation_id>/attachments")
@jwt_required()
def attachment_status(conversation_id):
    conv = owned_conversation(conversation_id, int(get_jwt_identity()))
    if not conv:
        return error("Conversation not found.", 404)
    return jsonify([doc.to_dict() for doc in conv.documents
                    if doc.user_id == conv.user_id and doc.status != "deleting"])


@api.delete("/chat/conversations/<int:conversation_id>")
@jwt_required()
def delete_conversation(conversation_id):
    conv = Conversation.query.filter_by(id=conversation_id, user_id=int(get_jwt_identity())).first()
    if not conv:
        return error("Conversation not found.", 404)
    db.session.delete(conv)
    db.session.commit()
    return jsonify({"message": "Conversation deleted."})


@api.patch("/chat/conversations/<int:conversation_id>")
@jwt_required()
def rename_conversation(conversation_id):
    conv = Conversation.query.filter_by(id=conversation_id, user_id=int(get_jwt_identity())).first()
    if not conv:
        return error("Conversation not found.", 404)
    title = (request.get_json(silent=True) or {}).get("title", "").strip()
    if not title:
        return error("A conversation title is required.")
    conv.title = title[:255]
    db.session.commit()
    return jsonify(conv.to_dict())


@api.post("/chat/conversations/<int:conversation_id>/messages")
@jwt_required()
def send_message(conversation_id):
    uid = int(get_jwt_identity())
    conv = Conversation.query.filter_by(id=conversation_id, user_id=uid).first()
    if not conv:
        return error("Conversation not found.", 404)
    question = ((request.get_json(silent=True) or {}).get("question") or "").strip()
    if not question or len(question) > 4000:
        return error("Question must contain 1 to 4000 characters.")
    recent = Message.query.filter_by(conversation_id=conv.id).order_by(Message.id.desc()).limit(12).all()
    history = []
    remaining = 6000
    for message in recent:
        content = message.content[:min(2000, remaining)]
        if message.sources:
            names = dict.fromkeys(source["document_name"] for source in message.sources)
            content += "\n\nFiles cited in this turn: " + ", ".join(names)[:500]
        history.append({"role": message.role, "content": content})
        remaining -= len(content)
        if remaining <= 0:
            break
    history.reverse()
    started = perf_counter()
    try:
        answer, sources = answer_question(uid, question, history, conversation_id=conv.id)
    except GroqError:
        raise
    except RuntimeError as exc:
        db.session.rollback()
        return error(str(exc), 503)
    user_message = Message(conversation_id=conv.id, role="user", content=question)
    assistant = Message(conversation_id=conv.id, role="assistant", content=answer, sources=sources)
    if conv.title == "New conversation":
        conv.title = question[:80]
    conv.updated_at = utcnow()
    db.session.add_all([user_message, assistant])
    db.session.commit()
    if current_app.config["DOCUMENT_JOBS"]:
        current_app.logger.info("Chat response duration=%.3fs citations=%s", perf_counter() - started, len(sources))
    return jsonify({"user_message": user_message.to_dict(), "answer": assistant.to_dict()})


@api.post("/chat/conversations/<int:conversation_id>/attachments")
@jwt_required()
def upload_attachments(conversation_id):
    return upload_documents(int(get_jwt_identity()), conversation_id)


@api.put("/chat/conversations/<int:conversation_id>/attachments/<int:document_id>")
@jwt_required()
def attach_existing(conversation_id, document_id):
    uid = int(get_jwt_identity())
    conv = owned_conversation(conversation_id, uid, lock=True)
    doc = owned_document(document_id, uid, lock=True) if conv else None
    if not doc or doc.file_type != "pdf":
        return error("Conversation or PDF not found.", 404)
    if doc not in conv.documents:
        if len(conv.documents) >= MAX_ATTACHMENTS:
            return error("This conversation already has 10 attachments.", 409)
        conv.documents.append(doc)
        conv.updated_at = utcnow()
    db.session.commit()
    return jsonify(doc.to_dict())


@api.delete("/chat/conversations/<int:conversation_id>/attachments/<int:document_id>")
@jwt_required()
def detach_document(conversation_id, document_id):
    uid = int(get_jwt_identity())
    conv = owned_conversation(conversation_id, uid, lock=True)
    doc = next((doc for doc in conv.documents if doc.id == document_id and doc.user_id == uid), None) if conv else None
    if not doc:
        return error("Attachment not found.", 404)
    conv.documents.remove(doc)
    conv.updated_at = utcnow()
    db.session.commit()
    return jsonify({"message": "PDF removed from conversation."})


@api.post("/ai/ask")
@jwt_required()
def ask():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question or len(question) > 4000:
        return error("Question must contain 1 to 4000 characters.")
    try:
        answer, sources = answer_question(int(get_jwt_identity()), question)
        return jsonify({"answer": answer, "sources": sources})
    except GroqError:
        raise
    except RuntimeError as exc:
        return error(str(exc), 503)


@api.post("/ai/summarize")
@jwt_required()
def ai_summarize():
    data = request.get_json(silent=True) or {}
    doc = owned_document(data.get("document_id"), int(get_jwt_identity())) if data.get("document_id") else None
    if not doc:
        return error("Document not found.", 404)
    try:
        if doc.status != "ready":
            return error(doc.error_message or "This document is still processing.", 409)
        source = file_source(doc)
        if source is None:
            return error("The original file is unavailable. Upload it again.", 409)
        pages = extract_pages(source, "." + doc.file_type)
        text = "\n".join(content for _, content in pages)
        return jsonify({"summary": summarize(text, bool(data.get("detailed"))), "document": doc.to_dict()})
    except GroqError:
        raise
    except RuntimeError as exc:
        return error(str(exc), 503)


@api.get("/search/documents")
@jwt_required()
def search_documents():
    request.args = request.args.copy()
    return documents()


@api.post("/search/semantic")
@jwt_required()
def semantic_search():
    from app.services.vectors import retrieve
    query = ((request.get_json(silent=True) or {}).get("query") or "").strip()
    if not query:
        return error("Search query is required.")
    try:
        hits = retrieve(int(get_jwt_identity()), query, 10)
        return jsonify([{**hit["metadata"], "text": hit["text"], "distance": hit["distance"]} for hit in hits])
    except RuntimeError as exc:
        return error(str(exc), 503)


@api.get("/dashboard/summary")
@jwt_required()
def dashboard():
    uid = int(get_jwt_identity())
    docs = Document.query.filter_by(user_id=uid).filter(Document.status != "deleting")
    return jsonify({"total_documents": docs.count(), "ready_documents": docs.filter_by(status="ready").count(),
                    "failed_documents": docs.filter_by(status="failed").count(),
                    "total_conversations": Conversation.query.filter_by(user_id=uid).count(),
                    "recent_documents": [d.to_dict() for d in docs.order_by(Document.created_at.desc()).limit(5).all()],
                    "recent_conversations": [c.to_dict() for c in Conversation.query.filter_by(user_id=uid).order_by(Conversation.updated_at.desc()).limit(5).all()]})
