from types import SimpleNamespace
from app.services import rag, vectors


def test_local_embedding_calls_ollama(app, monkeypatch):
    monkeypatch.setitem(app.config, "AI_PROVIDER", "ollama")
    monkeypatch.setitem(app.config, "OLLAMA_BASE_URL", "http://local-test")
    monkeypatch.setitem(app.config, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

    def fake_post(url, json, timeout):
        assert url == "http://local-test/api/embed"
        assert json["model"] == "nomic-embed-text"
        assert json["input"] == ["sample passage"]
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"embeddings": [[0.1, 0.2, 0.3]]})

    monkeypatch.setattr(vectors.requests, "post", fake_post)
    with app.app_context():
        assert vectors.embed(["sample passage"]) == [[0.1, 0.2, 0.3]]


def test_local_chat_uses_ollama(app, monkeypatch):
    monkeypatch.setitem(app.config, "AI_PROVIDER", "ollama")
    monkeypatch.setitem(app.config, "OLLAMA_BASE_URL", "http://local-test")
    monkeypatch.setitem(app.config, "OLLAMA_CHAT_MODEL", "qwen2.5:3b")

    def fake_post(url, json, timeout):
        assert url == "http://local-test/api/chat"
        assert json["model"] == "qwen2.5:3b"
        assert json["stream"] is False
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"message": {"content": "Answer from local model."}})

    monkeypatch.setattr(rag.requests, "post", fake_post)
    with app.app_context():
        assert rag._complete("system", "question") == "Answer from local model."
