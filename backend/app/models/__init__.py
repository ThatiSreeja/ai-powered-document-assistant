from datetime import datetime, timezone
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db

conversation_documents = db.Table(
    "conversation_documents",
    db.Column("conversation_id", db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
    db.Column("document_id", db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True),
)

def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}


class Document(db.Model):
    __tablename__ = "documents"
    __table_args__ = (db.UniqueConstraint("user_id", "content_hash", name="uq_documents_owner_hash"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    file_type = db.Column(db.String(10), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), default="processing", nullable=False, index=True)
    error_message = db.Column(db.String(500))
    content_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "name": self.original_name, "type": self.file_type,
                "size": self.file_size, "status": self.status, "error": self.error_message,
                "created_at": self.created_at.isoformat()}


class Conversation(db.Model):
    __tablename__ = "conversations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(255), default="New conversation", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    messages = db.relationship("Message", backref="conversation", cascade="all, delete-orphan", lazy="select")
    documents = db.relationship("Document", secondary=conversation_documents, order_by=Document.id, backref="conversations")

    def to_dict(self, include_messages=False):
        result = {"id": self.id, "title": self.title, "created_at": self.created_at.isoformat()}
        if include_messages:
            result["messages"] = [m.to_dict() for m in sorted(self.messages, key=lambda message: message.created_at)]
        return result


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "role": self.role, "content": self.content,
                "sources": self.sources or [], "created_at": self.created_at.isoformat()}


class ProcessingLog(db.Model):
    __tablename__ = "document_processing_logs"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    message = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
