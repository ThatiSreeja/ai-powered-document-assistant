# Architecture

Paperwise is a React single page application and a Flask JSON API. The browser sends a JWT with protected requests. Flask stores accounts, documents, conversation messages, and processing logs in MySQL. Uploaded file bytes stay on the backend filesystem under a generated, user-scoped filename. ChromaDB persists embeddings and chunk metadata separately.

```text
React + Axios → Flask blueprints → MySQL
                               ↘ document parsers → local MiniLM embeddings → persistent ChromaDB
                               ↘ Groq routing → general chat or retrieval and cited answer
```

The user ID is attached to every stored chunk and required as a ChromaDB search filter. Relational document and conversation lookups also include the authenticated user ID. The React app stores its short-lived access token in localStorage; logout removes it. Production deployments should use HTTPS and consider moving to secure same-site cookies.

## RAG workflow, in plain language

The backend creates MiniLM embeddings for overlapping passages and stores them in ChromaDB. Groq routes each question using recent conversation history. General questions go straight to chat completion. Document questions use a rewritten query to find relevant passages in the authenticated user's library. Groq receives those passages and generates a cited response. Mixed questions can include a separate general-knowledge explanation. MySQL persists the conversation and validated citation references.

## Important configuration

The initial implementation uses a 1,000-character chunk and 150-character overlap, retrieves at most six passages, and filters cosine distance at 0.55. Tune these values against a representative document set before production. Synchronous file processing is suitable for local development; a task queue is recommended for large scale. Chroma metadata uses integer IDs and a persistent local directory, which must be on a durable volume in deployment. Local inference avoids API charges but requires model downloads, disk space, and sufficient memory/CPU or GPU.
