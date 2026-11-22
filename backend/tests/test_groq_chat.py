import io
import json
from pathlib import Path

import httpx
import pymupdf
import pytest
from groq import Groq

from app.services import groq_chat, vectors
from app.models import Document
from app.services.chat import MISSING


@pytest.fixture(autouse=True)
def configure_groq(app, monkeypatch):
    monkeypatch.setitem(app.config, "AI_PROVIDER", "groq")
    monkeypatch.setitem(app.config, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(vectors, "embed", lambda texts: [[1.0, 0.0] for _ in texts])


def mock_groq(monkeypatch, *replies):
    calls = []
    remaining = iter(replies)

    def handle(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        calls.append(json.loads(request.content))
        reply = next(remaining)
        if reply == "timeout":
            raise httpx.ReadTimeout("private upstream information", request=request)
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": {"message": "private upstream information"}})
        content = json.dumps(reply) if isinstance(reply, dict) else reply
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    monkeypatch.setattr(groq_chat, "Groq", lambda **options: Groq(
        **options, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    return calls


def create_conversation(client, auth):
    response = client.post("/api/chat/conversations", headers=auth, json={})
    assert response.status_code == 201
    return f"/api/chat/conversations/{response.json['id']}"


def ask(client, auth, question, conversation=None):
    path = f"{conversation}/messages" if conversation else "/api/ai/ask"
    return client.post(path, headers=auth, json={"question": question})


def pdf(text, page_number=1):
    with pymupdf.open() as file:
        for _ in range(page_number):
            page = file.new_page()
        page.insert_text((72, 72), text)
        return io.BytesIO(file.tobytes())


def test_general_and_python_follow_up(client, auth, monkeypatch):
    calls = mock_groq(monkeypatch, {"mode": "general"}, "A stack uses last-in, first-out order.",
                      {"mode": "general"}, "```python\nstack = []\n```")
    conversation = create_conversation(client, auth)
    first = ask(client, auth, "What is a stack?", conversation)
    second = ask(client, auth, "Show me how to create one in Python.", conversation)
    assert first.status_code == second.status_code == 200
    assert second.json["answer"]["content"].startswith("```python")
    assert second.json["answer"]["sources"] == []
    assert calls[2]["messages"][1]["content"] == "What is a stack?"
    assert calls[3]["messages"][2]["content"] == first.json["answer"]["content"]
    assert len(client.get(conversation, headers=auth).json["messages"]) == 4


def test_multi_pdf_follow_up_mixed_missing_privacy_and_deletion(client, auth, monkeypatch):
    conversation = create_conversation(client, auth)
    response = client.post(conversation + "/attachments", headers=auth, data={"files": [
        (pdf("The Alpha launch is June 12.", 2), "alpha.pdf"),
        (pdf("The Beta launch is July 24."), "beta.pdf"),
    ]})
    assert response.status_code == 201
    assert [row["status"] for row in response.json] == ["ready", "ready"]
    alpha, beta = [row["id"] for row in response.json]
    document = {"mode": "document", "query": "launch date", "document_ids": [alpha, beta]}
    calls = mock_groq(monkeypatch, document, {"document_answer": "Beta launches July 24. Alpha launches June 12.", "source_indices": [1, 2]},
                      {"mode": "mixed", "query": "Alpha launch date", "document_ids": [alpha]},
                      {"document_answer": "Alpha launches June 12 [Source 1].", "general_answer": "Use an ISO date."},
                      {"mode": "document", "query": "Alpha launch budget", "document_ids": [alpha]},
                      {"document_answer": "A claim with an invalid citation [Source 77]."},
                      {"mode": "general"}, "A stack uses LIFO order.",
                      {"mode": "document", "query": "Alpha launch date", "document_ids": [alpha]},
                      {"mode": "document", "query": "Alpha launch date", "document_ids": [alpha]})
    answer = ask(client, auth, "When do Alpha and Beta launch?", conversation).json["answer"]
    assert {row["document_name"]: row["page_number"] for row in answer["sources"]} == {"alpha.pdf": 2, "beta.pdf": 1}
    follow_up = ask(client, auth, "For the first project I mentioned, how do I format its date?", conversation).json["answer"]
    assert "## General knowledge" in follow_up["content"]
    assert follow_up["sources"][0]["document_id"] == alpha
    assert calls[2]["messages"][1]["content"] == "When do Alpha and Beta launch?"
    missing = ask(client, auth, "What is Alpha's budget?", conversation).json["answer"]
    assert missing["content"] == MISSING and not missing["sources"]
    assert ask(client, auth, "What is a stack?").json["sources"] == []

    account = client.post("/api/auth/register", json={"name": "Other", "email": "other@example.com", "password": "long-password"})
    other = {"Authorization": "Bearer " + account.json["access_token"]}
    assert client.get("/api/documents", headers=other).json == []
    assert client.get(conversation, headers=other).status_code == 404
    assert client.delete(f"/api/documents/{alpha}", headers=other).status_code == 404
    assert ask(client, other, "When does Alpha launch?").json["answer"] == MISSING
    assert "alpha.pdf" not in calls[-1]["messages"][-1]["content"]
    assert client.delete(f"/api/documents/{alpha}", headers=auth).status_code == 200
    assert vectors._collection().get(where={"document_id": alpha})["ids"] == []
    assert vectors._collection().get(where={"document_id": beta})["ids"]
    assert ask(client, auth, "When does Alpha launch?").json["answer"] == MISSING


def test_invalid_and_oversized_pdf(client, auth, app):
    attachments = create_conversation(client, auth) + "/attachments"
    invalid = client.post(attachments, headers=auth, data={"files": (io.BytesIO(b"invalid"), "fake.pdf")})
    assert invalid.json[0]["error"] == "The file is not a valid PDF."
    damaged = client.post(attachments, headers=auth, data={"files": (io.BytesIO(b"%PDF-1.7\ninvalid"), "damaged.pdf")})
    assert damaged.json[0]["status"] == "failed"
    app.config["MAX_PDF_PAGES"] = 1
    too_many_pages = client.post(attachments, headers=auth, data={"files": (pdf("page two", 2), "large.pdf")})
    assert "1-page limit" in too_many_pages.json[0]["error"]


def test_reupload_restores_lost_pdf_and_summary(app, client, auth, monkeypatch):
    chat = create_conversation(client, auth)
    original = pdf("Kestrel uses a PostgreSQL database.").getvalue()
    upload = client.post(chat + "/attachments", headers=auth,
                         data={"files": (io.BytesIO(original), "Kestrel.pdf")})
    document_id = upload.json[0]["id"]
    document = Document.query.filter_by(id=document_id).one()
    (Path(app.config["UPLOAD_FOLDER"]) / document.stored_name).unlink()
    vectors.delete_document(document_id)

    restored = client.post(chat + "/attachments", headers=auth,
                           data={"files": (io.BytesIO(original), "Kestrel.pdf")})
    assert restored.json[0]["id"] == document_id
    assert restored.json[0]["status"] == "ready"
    assert len(client.get(chat, headers=auth).json["attachments"]) == 1
    mock_groq(monkeypatch, {"mode": "document", "overview": True},
              {"document_answer": "Kestrel uses PostgreSQL [Source 1]."})
    answer = ask(client, auth, "Summarize the PDF.", chat).json["answer"]
    assert answer["sources"][0]["document_id"] == document_id


def test_attachments_are_reused_and_scoped_to_conversation(client, auth, monkeypatch):
    first = create_conversation(client, auth)
    second = create_conversation(client, auth)
    pdf_bytes = pdf("Kestrel uses a PostgreSQL database.", 2).getvalue()
    upload = client.post(first + "/attachments", headers=auth,
                         data={"files": (io.BytesIO(pdf_bytes), "Kestrel project.pdf")})
    assert upload.json[0]["name"] == "Kestrel project.pdf"
    document_id = upload.json[0]["id"]
    duplicate = client.post(first + "/attachments", headers=auth,
                            data={"files": (io.BytesIO(pdf_bytes), "duplicate.pdf")})
    assert duplicate.json[0]["id"] == document_id
    assert vectors._collection().count() == 1
    assert len(client.get(first, headers=auth).json["attachments"]) == 1
    assert not client.get(second, headers=auth).json["attachments"]

    calls = mock_groq(monkeypatch, {"mode": "general", "query": "Kestrel database"},
                      {"document_answer": "Kestrel uses PostgreSQL [Source 1]."},
                      {"mode": "document", "document_ids": [document_id]},
                      {"mode": "document", "overview": True},
                      {"document_answer": "Kestrel uses PostgreSQL [Source 1]."},
                      {"mode": "document", "document_ids": [document_id]})
    grounded = ask(client, auth, "What database does Kestrel use?", first).json["answer"]
    assert grounded["sources"][0]["page_number"] == 2
    assert ask(client, auth, "What does the Kestrel PDF say?", second).json["answer"]["content"] == MISSING
    assert "Kestrel project.pdf" not in calls[2]["messages"][-1]["content"]
    assert client.put(f"{second}/attachments/{document_id}", headers=auth).status_code == 200
    assert ask(client, auth, "Summarize all PDFs.", second).json["answer"]["sources"]
    assert json.loads(calls[4]["messages"][-1]["content"])["overview"] is True
    assert client.delete(f"{first}/attachments/{document_id}", headers=auth).status_code == 200
    assert ask(client, auth, "What does the PDF say?", first).json["answer"]["content"] == MISSING
    assert len(client.get(second, headers=auth).json["attachments"]) == 1

    account = client.post("/api/auth/register", json={"name": "Other", "email": "viewer@example.com", "password": "long-password"})
    other = {"Authorization": "Bearer " + account.json["access_token"]}
    other_chat = create_conversation(client, other)
    url = f"/api/documents/{document_id}/pdf"
    with client.get(url, headers=auth) as response:
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF-")
    assert client.get(url, headers=other).status_code == 404
    assert client.put(f"{other_chat}/attachments/{document_id}", headers=other).status_code == 404
    assert client.post(first + "/attachments", headers=other,
                       data={"files": (io.BytesIO(pdf_bytes), "Kestrel.pdf")}).status_code == 404
    assert client.delete(f"/api/documents/{document_id}", headers=auth).status_code == 200
    assert client.get(second, headers=auth).json["attachments"] == []


def test_existing_document_and_conversation_endpoints(client, auth, monkeypatch):
    mock_groq(monkeypatch, "Alpha launches on June 12.")
    upload = client.post("/api/documents", headers=auth, data={"files": (pdf("Alpha launches on June 12."), "alpha.pdf")})
    document_id = upload.json[0]["id"]
    url = f"/api/documents/{document_id}"
    assert client.get(url, headers=auth).json["status"] == "ready"
    assert client.post(url + "/reprocess", headers=auth).json["status"] == "ready"
    assert client.get("/api/search/documents?q=alpha", headers=auth).json[0]["id"] == document_id
    search = client.post("/api/search/semantic", headers=auth, json={"query": "launch"})
    assert search.json[0]["document_id"] == document_id
    summary = client.post("/api/ai/summarize", headers=auth, json={"document_id": document_id})
    assert "June 12" in summary.json["summary"]
    conversation = create_conversation(client, auth)
    assert client.patch(conversation, headers=auth, json={"title": "Launch"}).json["title"] == "Launch"
    assert client.get("/api/chat/conversations", headers=auth).json[0]["title"] == "Launch"
    assert client.get("/api/dashboard/summary", headers=auth).json["ready_documents"] == 1
    assert client.delete(conversation, headers=auth).status_code == 200
    assert client.post("/api/auth/logout", headers=auth).status_code == 200


@pytest.mark.parametrize(("failure", "status"), [(429, 429), (500, 503), ("timeout", 504), (401, 503)])
def test_upstream_errors_are_sanitized_and_leave_history_unchanged(client, auth, monkeypatch, failure, status):
    mock_groq(monkeypatch, failure)
    conversation = create_conversation(client, auth)
    response = ask(client, auth, "What is Python?", conversation)
    assert response.status_code == status
    assert "private upstream information" not in response.json["error"]
    assert client.get(conversation, headers=auth).json["messages"] == []
