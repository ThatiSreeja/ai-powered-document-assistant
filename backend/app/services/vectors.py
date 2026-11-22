import chromadb
import numpy as np
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
from flask import current_app
from functools import lru_cache
from heapq import nsmallest
from pathlib import Path
from threading import Lock
from openai import OpenAI
from sqlalchemy import delete, func, insert, select, tuple_
from app.extensions import db
from app.models import Document, DocumentChunk, DocumentFile
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


def _model_name():
    provider = _provider()
    model = {"local": "all-MiniLM-L6-v2", "ollama": current_app.config["OLLAMA_EMBEDDING_MODEL"],
             "openai": current_app.config["OPENAI_EMBEDDING_MODEL"]}[provider]
    return f"{provider}_{model}"


def _collection():
    client = chromadb.PersistentClient(path=current_app.config["CHROMA_PATH"])
    suffix = re.sub(r"[^a-zA-Z0-9_-]", "_", _model_name())[:48]
    return client.get_or_create_collection(f"chunks_{suffix}", metadata={"hnsw:space": "cosine"})


def embed(texts):
    provider = _provider()
    if provider == "local":
        try:
            cache = current_app.config["EMBEDDING_CACHE_PATH"]
            bundled = current_app.config["EMBEDDING_BUNDLED_CACHE"]
            model_dir = Path(ONNXMiniLM_L6_V2.MODEL_NAME) / "onnx" / "model.onnx"
            if bundled and not (cache / model_dir).is_file():
                cache = Path(bundled)
            batch_size = current_app.config["LOCAL_EMBEDDING_BATCH_SIZE"]
            results = []
            for start in range(0, len(texts), batch_size):
                with _model_lock:
                    results.extend(_local_model(cache)(texts[start:start + batch_size]))
            return results
        except Exception:
            raise RuntimeError("The local embedding model is unavailable. Check the backend model cache and network.") from None
    if provider == "ollama":
        url = current_app.config["OLLAMA_BASE_URL"] + "/api/embed"
        model = current_app.config["OLLAMA_EMBEDDING_MODEL"]
        try:
            response = requests.post(url, json={"model": model, "input": texts}, timeout=(5, 120))
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
    client = OpenAI(api_key=key, timeout=45, max_retries=0)
    vectors = []
    for offset in range(0, len(texts), 64):
        response = client.embeddings.create(
            model=current_app.config["OPENAI_EMBEDDING_MODEL"], input=texts[offset:offset + 64]
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    return vectors


def embed_chunks(chunks):
    texts = list(dict.fromkeys(chunk["text"] for chunk in chunks))
    vectors = []
    for start in range(0, len(texts), 64):
        batch = texts[start:start + 64]
        embedded = embed(batch)
        if len(embedded) != len(batch):
            raise RuntimeError("The embedding service returned incomplete results. Retry this document.")
        vectors.extend(embedded)
    by_text = dict(zip(texts, vectors))
    return [by_text[chunk["text"]] for chunk in chunks]


def store_chunks(document_id, chunks, vectors):
    db.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    model = _model_name()
    db.session.execute(insert(DocumentChunk), [
        {"document_id": document_id, "position": index, "page_number": chunk["page_number"],
         "content": chunk["text"], "embedding": _unit_vector(vector).tobytes(),
         "model": model}
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ])


def _unit_vector(vector):
    array = np.asarray(vector, dtype="<f4")
    norm = np.linalg.norm(array)
    return array / norm if norm else array


def add_document(document, chunks):
    vectors = embed_chunks(chunks)
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
    if current_app.config["DOCUMENT_JOBS"]:
        indexed, legacy = _document_ids(user_id, document_ids)
        if not indexed:
            return _retrieve_legacy(user_id, question, limit, legacy, max_distance, across_documents)
        query = np.asarray(embed([question])[0], dtype="<f4")
        groups = [[doc_id] for doc_id in (indexed + legacy)[:10]] if across_documents else [indexed + legacy]
        rows = []
        for group in groups:
            group_limit = 2 if len(groups) > 1 else limit
            hits = _stored_hits(query, user_id, [doc for doc in group if doc in indexed], group_limit, max_distance)
            legacy_group = [doc for doc in group if doc in legacy]
            if legacy_group:
                hits += _retrieve_legacy(user_id, question, group_limit, legacy_group, max_distance, False, [query.tolist()])
            rows.extend(nsmallest(group_limit, hits, key=lambda hit: hit["distance"]))
        return rows
    return _retrieve_legacy(user_id, question, limit, document_ids, max_distance, across_documents)


def _document_ids(user_id, document_ids):
    query = select(Document.id, DocumentFile.document_id).outerjoin(DocumentFile).where(
        Document.user_id == user_id, Document.status == "ready")
    if document_ids is not None:
        query = query.where(Document.id.in_(document_ids))
    indexed, legacy = [], []
    for document_id, stored in db.session.execute(query.order_by(Document.id.desc())):
        (indexed if stored is not None else legacy).append(document_id)
    return indexed, legacy


def _stored_hits(query, user_id, document_ids, limit, max_distance):
    if not document_ids:
        return []
    statement = select(DocumentChunk.document_id, DocumentChunk.position, DocumentChunk.embedding).join(Document).where(
        Document.user_id == user_id, Document.status == "ready",
        Document.id.in_(document_ids), DocumentChunk.model == _model_name(),
    ).execution_options(yield_per=128)
    query = _unit_vector(query)
    if not query.any():
        return []

    def matches():
        for batch in db.session.execute(statement).partitions():
            embeddings = [(document_id, position, np.frombuffer(raw, dtype="<f4"))
                          for document_id, position, raw in batch if len(raw) == query.nbytes]
            if not embeddings:
                continue
            distances = 1 - np.clip(np.stack([row[2] for row in embeddings]) @ query, -1, 1)
            for (document_id, position, embedding), distance in zip(embeddings, distances):
                if distance <= max_distance and embedding.any():
                    yield float(distance), document_id, position

    selected = nsmallest(limit, matches())
    if not selected:
        return []
    keys = [(document_id, position) for _, document_id, position in selected]
    passages = {
        (document_id, position): {"text": content, "metadata": {
            "document_id": document_id, "document_name": name, "page_number": page_number,
        }}
        for document_id, position, content, page_number, name in db.session.execute(select(
            DocumentChunk.document_id, DocumentChunk.position, DocumentChunk.content,
            DocumentChunk.page_number, Document.original_name,
        ).join(Document).where(
            Document.user_id == user_id, Document.status == "ready",
            tuple_(DocumentChunk.document_id, DocumentChunk.position).in_(keys),
        ))
    }
    return [{**passages[key], "distance": hit[0]} for hit, key in zip(selected, keys) if key in passages]


def _stored_passage(chunk, name):
    return {"text": chunk.content, "metadata": {"document_id": chunk.document_id,
            "document_name": name, "page_number": chunk.page_number}}


def _retrieve_legacy(user_id, question, limit, document_ids, max_distance, across_documents, query_embedding=None):
    if document_ids == []:
        return []
    collection = _collection()
    count = collection.count()
    if count == 0:
        return []
    if query_embedding is None:
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
        if current_app.config["DOCUMENT_JOBS"]:
            indexed, document_ids = _document_ids(user_id, document_ids)
            for document_id in indexed:
                base = select(DocumentChunk, Document.original_name).join(Document).where(
                    Document.id == document_id, Document.user_id == user_id, Document.status == "ready",
                    DocumentChunk.model == _model_name())
                count = db.session.scalar(select(func.count()).select_from(base.subquery()))
                positions = [round(i * (count - 1) / (samples - 1)) for i in range(samples)]
                if count > samples:
                    base = base.where(DocumentChunk.position.in_(positions))
                rows.extend(_stored_passage(chunk, name) for chunk, name in db.session.execute(
                    base.order_by(DocumentChunk.position)))
            if not document_ids:
                return rows
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
