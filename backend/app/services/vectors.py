import chromadb
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
from flask import current_app
from functools import lru_cache
from pathlib import Path
from threading import Lock
from openai import OpenAI
import requests
import re

_model_lock = Lock()


def _provider():
    configured = current_app.config["EMBEDDING_PROVIDER"]
    chat_provider = current_app.config["AI_PROVIDER"]
    return configured or ("local" if chat_provider == "groq" else chat_provider)


@lru_cache(maxsize=4)
def _local_model(cache_path):
    model = ONNXMiniLM_L6_V2()
    model.DOWNLOAD_PATH = Path(cache_path) / model.MODEL_NAME
    model(["warm up the embedding model"])
    return model


def _collection():
    client = chromadb.PersistentClient(path=current_app.config["CHROMA_PATH"])
    provider = _provider()
    model = {"local": "all-MiniLM-L6-v2", "ollama": current_app.config["OLLAMA_EMBEDDING_MODEL"],
             "openai": current_app.config["OPENAI_EMBEDDING_MODEL"]}[provider]
    suffix = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{provider}_{model}")[:48]
    return client.get_or_create_collection(f"chunks_{suffix}", metadata={"hnsw:space": "cosine"})


def embed(texts):
    provider = _provider()
    if provider == "local":
        try:
            with _model_lock:
                model = _local_model(current_app.config["EMBEDDING_CACHE_PATH"])
            return model(texts)
        except Exception:
            raise RuntimeError("The local embedding model is unavailable. Check the backend model cache and network.") from None
    if provider == "ollama":
        url = current_app.config["OLLAMA_BASE_URL"] + "/api/embed"
        model = current_app.config["OLLAMA_EMBEDDING_MODEL"]
        try:
            response = requests.post(url, json={"model": model, "input": texts}, timeout=(5, 300))
        except requests.ConnectionError as exc:
            raise RuntimeError("Ollama is not running. Start Ollama, then retry processing.") from exc
        if response.status_code == 404:
            raise RuntimeError(f"Ollama embedding model '{model}' is not installed. Run: ollama pull {model}")
        response.raise_for_status()
        return response.json()["embeddings"]

    if provider != "openai":
        raise RuntimeError("EMBEDDING_PROVIDER must be 'local', 'ollama', or 'openai'.")
    key = current_app.config.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=key)
    vectors = []
    for offset in range(0, len(texts), 64):
        response = client.embeddings.create(
            model=current_app.config["OPENAI_EMBEDDING_MODEL"], input=texts[offset:offset + 64]
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    return vectors


def add_document(document, chunks):
    vectors = []
    for start in range(0, len(chunks), 64):
        vectors.extend(embed([c["text"] for c in chunks[start:start + 64]]))
    _collection().upsert(
        ids=[f"{document.id}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[{"user_id": document.user_id, "document_id": document.id,
                     "document_name": document.original_name, "page_number": c["page_number"] or 0}
                   for c in chunks],
    )


def delete_document(document_id):
    client = chromadb.PersistentClient(path=current_app.config["CHROMA_PATH"])
    for entry in client.list_collections():
        name = entry if isinstance(entry, str) else entry.name
        client.get_collection(name).delete(where={"document_id": document_id})


def retrieve(user_id, question, limit=6, *, document_ids=None, max_distance=0.55, across_documents=False):
    try:
        return _retrieve(user_id, question, limit, document_ids, max_distance, across_documents)
    except RuntimeError:
        raise
    except Exception:
        current_app.logger.warning("Semantic search failed", exc_info=False)
        raise RuntimeError("Document search is unavailable. Please retry.") from None


def _retrieve(user_id, question, limit, document_ids, max_distance, across_documents):
    if document_ids == []:
        return []
    collection = _collection()
    count = collection.count()
    if count == 0:
        return []
    query_embedding = embed([question])
    groups = [[doc_id] for doc_id in document_ids[:10]] if across_documents and document_ids else [document_ids]
    rows = []
    for group in groups:
        where = {"user_id": user_id}
        if group:
            where = {"$and": [where, {"document_id": {"$in": group}}]}
        result = collection.query(query_embeddings=query_embedding, n_results=min(2 if len(groups) > 1 else limit, count),
                                  where=where, include=["documents", "metadatas", "distances"])
        for text, metadata, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
            if distance <= max_distance:
                rows.append({"text": text, "metadata": metadata, "distance": distance})
    return rows


def overview(user_id, document_ids):
    if not document_ids:
        return []
    rows = []
    samples = min(10, max(2, 36 // len(document_ids)))
    try:
        collection = _collection()
        for document_id in document_ids:
            data = collection.get(where={"$and": [{"user_id": user_id}, {"document_id": document_id}]},
                                  include=["documents", "metadatas"])
            chunks = sorted(zip(data["ids"], data["documents"], data["metadatas"]),
                            key=lambda row: int(row[0].rsplit(":", 1)[-1]))
            if len(chunks) > samples:
                chunks = [chunks[round(index * (len(chunks) - 1) / (samples - 1))] for index in range(samples)]
            for _, text, metadata in chunks:
                rows.append({"text": text, "metadata": metadata})
    except Exception:
        raise RuntimeError("Document passages are unavailable. Please retry.") from None
    return rows
