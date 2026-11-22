from types import SimpleNamespace
from app.services import rag


def test_answer_cites_retrieved_document(app, monkeypatch):
    monkeypatch.setitem(app.config, "AI_PROVIDER", "openai")
    monkeypatch.setitem(app.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(app.config, "OPENAI_CHAT_MODEL", "test-model")
    monkeypatch.setattr(rag, "retrieve", lambda _uid, _question: [{
        "text": "The launch date is June 12.",
        "metadata": {"document_id": 9, "document_name": "launch.txt", "page_number": 2},
        "distance": 0.1,
    }])

    class FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="The launch is June 12 [Source 1]."))])

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(rag, "OpenAI", FakeOpenAI)
    with app.app_context():
        answer, sources = rag.answer_question(3, "When is launch?")
    assert "[Source 1]" in answer
    assert sources == [{"index": 1, "document_id": 9, "document_name": "launch.txt", "page_number": 2}]
