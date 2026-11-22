# Paperwise — AI-Powered Document Assistant

Paperwise answers general questions with Groq and retrieves passages from your PDF, DOCX and TXT files when a question calls for document evidence. It preserves conversation context, cites source files and pages, and can add general knowledge alongside a document answer.

## Features

- Password-hashed registration and JWT-protected API
- User-scoped file library, processing status, filters and deletion
- PDF page extraction, DOCX/TXT extraction, overlapping text chunks
- Groq chat and local MiniLM embeddings with persistent document storage
- Source-cited RAG conversations, history, and document summaries API
- Multi-PDF attachments in chat, with drag-and-drop, library reuse, and conversation-specific retrieval
- Dashboard metrics, responsive React interface, rate limiting and health check

## Stack and layout

React 18, JavaScript, Vite, Tailwind CSS, React Router, Axios, Flask, SQLAlchemy, Flask-Migrate, JWT, PostgreSQL, ChromaDB and the Groq Python SDK. Existing local MySQL 8 deployments are also supported. See [architecture](docs/architecture.md), [database design](docs/database_design.md), [API docs](docs/api_documentation.md), and [RAG pipeline](docs/rag_pipeline.md).

```text
backend/app/{models,routes,services}/  Flask API and RAG services
frontend/src/                          React user interface
database/schema.sql                    MySQL database creation
docs/                                  Architecture and API notes
```

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer with npm
- PostgreSQL running locally or remotely, or an existing MySQL 8 database
- A [Groq API key](https://console.groq.com/keys)
- Network access to download the local MiniLM embedding model on first use

## Local setup

1. Copy `backend/.env.example` to `backend/.env` if needed. Set `GROQ_API_KEY`, `SECRET_KEY`, `JWT_SECRET_KEY`, and `DATABASE_URL` in the backend file. Keep it private.
2. Create an empty PostgreSQL database and point `DATABASE_URL` to it. If you use MySQL 8 locally, create its database using `database/schema.sql` or use your existing database URL.
3. From `backend/`, create a virtual environment and run `python -m pip install -r requirements.txt`. Apply migrations with `python -m flask --app run db upgrade`.
4. From `backend/`, start the API with `python run.py`. It listens at `http://localhost:5000`.
5. From `frontend/`, run `npm ci` and `npm run dev`. Open `http://localhost:5173`.

Groq defaults to `openai/gpt-oss-120b`. Set `GROQ_CHAT_MODEL` to another Groq chat model that supports JSON object mode. `GROQ_TIMEOUT_SECONDS` is the per-request timeout. Groq receives the recent conversation and relevant excerpts for document questions. The embedding model runs in the backend process and uses `EMBEDDING_CACHE_PATH` when set.

If you already indexed files with Ollama, set `EMBEDDING_PROVIDER=ollama` and retain the existing `OLLAMA_EMBEDDING_MODEL` and Chroma path to keep using those vectors with Groq chat. To switch the embedding model to MiniLM, reprocess the existing files from the document library. `AI_PROVIDER=ollama` and `AI_PROVIDER=openai` remain available for the previous document-chat behavior.

## PDF attachments in chat

Use the paperclip or drop PDFs onto the composer. You can attach existing PDFs from the inline library picker. A conversation accepts up to ten PDFs. Uploaded files, attachment links, and chat history persist across sign-ins. The remove button detaches the PDF from the conversation. The trash button permanently deletes it from the library, all conversations, and Chroma.

Use `python -m flask --app run db upgrade` before running this version against an existing database. Previous conversations retain their messages and citations. Use the library picker to attach older PDFs to the appropriate conversation.

## Tests

Backend: from `backend/`, run `pytest`. Tests use in-memory SQLite and mocks for model calls; no API key or paid request is needed. Frontend: from `frontend/`, run `npm test`. Production build: `npm run build`.

## Deployment preparation

`render.yaml` provisions a Docker web service, a persistent disk for PDFs and Chroma, and a private PostgreSQL database in Oregon. The Blueprint supplies the internal connection string as `DATABASE_URL`. Set `GROQ_API_KEY` in Render and keep the generated `SECRET_KEY` and `JWT_SECRET_KEY` stable. The container serves the frontend and API on the same origin and runs `python -m flask --app run db upgrade` before starting Gunicorn. A newly provisioned database and disk start empty.

`render-free.yaml` provisions a free web service and a private free Render PostgreSQL instance in the same workspace. It sets `DATABASE_URL` automatically. The free database keeps accounts across web-service restarts and redeploys and expires after 30 days. To use externally hosted PostgreSQL instead, set the service?s `DATABASE_URL` to that connection string in Render. When upgrading a demo that used SQLite, migrate any surviving account data before switching databases if you need to preserve existing sign-ins. New uploads, embeddings, and pending jobs live in PostgreSQL. Legacy files and Chroma indexes created on temporary storage remain subject to filesystem resets.

To keep an existing Render URL, upgrade that web service to a plan that supports persistent disks and attach a disk at `/var/data`. Create a dedicated PostgreSQL database in the service's region and use its **Internal Database URL** for the backend's `DATABASE_URL`. Use the storage paths in `render.yaml`. Before changing settings that can restart an existing service, back up any available SQLite database, uploaded files, and Chroma directory. Preserving existing sign-ins requires importing their original account rows and password hashes along with any related application records before switching traffic. A new PostgreSQL database cannot recover files or accounts already lost from ephemeral storage.

The relational schema contains `users`, `documents`, `document_processing_logs`, `conversations`, `messages`, `conversation_documents`, and `revoked_tokens`, plus Alembic's `alembic_version`. To exercise restart and migration tests against PostgreSQL, set `PAPERWISE_TEST_POSTGRES_URL` to a test database whose user can create schemas, then run `python -m pytest` from `backend/`.

On Render, PDF uploads and normalized retrieval vectors are stored in PostgreSQL in `document_files` and `document_chunks`. The Docker service starts up to two background workers after migrations. PostgreSQL keeps accepted jobs across process restarts. Abandoned jobs become eligible for reassignment after five minutes. The same workers retry cleanup for deleted documents. `DOCUMENT_WORKERS` accepts 1 or 2. The Docker image bundles the MiniLM model. On Render, local inference runs in batches of 8 by default to limit peak memory. Set LOCAL_EMBEDDING_BATCH_SIZE to an integer from 1 to 32 to override it. The existing web service runs the workers. Background processing is enabled by default locally and on Render. Run `python run.py` after migrating. With a manual Gunicorn startup, use `--config gunicorn.conf.py` to start the job workers.

Older uploads may still be on the former filesystem. Retry processing to copy an available original into PostgreSQL, or re-upload the original bytes to restore a missing file while keeping its document ID and attachments. Back up existing originals before redeploying a free instance. PostgreSQL storage shares the selected database plan’s size limit and lifetime.

Browser sign-in uses an HTTP-only session cookie with a one-hour token lifetime and CSRF protection. Paperwise restores an active session when a page reloads. Signing out revokes that session in PostgreSQL. On the first visit after upgrading from browser-stored tokens, sign in once using your existing email and password.

For separate frontend and backend services, use the manual setup below.

1. Link the Paperwise Git repository to a Render Python web service. Use `backend/` as the root directory and `python -m pip install -r requirements.txt` as the build command.
2. Set `GROQ_API_KEY`, `SECRET_KEY`, `JWT_SECRET_KEY`, and `DATABASE_URL` in the backend service's Environment settings. Use the persistent PostgreSQL internal URL when the services share a region. Set `CORS_ORIGINS` to the exact HTTPS frontend origin. Set `AUTH_COOKIE_SECURE=true`. If the frontend and backend are on different sites, set `AUTH_COOKIE_SAMESITE=None`. Browsers that block third-party cookies can require a same-site domain or same-origin hosting.
3. Attach a persistent disk to the backend at `/var/data`. Set `UPLOAD_FOLDER=/var/data/uploads`, `CHROMA_PATH=/var/data/chroma`, and `EMBEDDING_CACHE_PATH=/var/data/models`. Keep the uploads and Chroma paths from the current deployment if it already has indexed files. [Render persistent disks](https://render.com/docs/disks)
4. Use `python -m flask --app run db upgrade && gunicorn --config gunicorn.conf.py --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT run:app` as the start command. A single worker process shares the embedded Chroma client across its threads. Set the health check path to `/api/health`.
5. Use `frontend/` as the root directory for the static site. Build with `npm ci --include=dev && npm run build`, publish `dist`, set `VITE_API_URL` to the backend HTTPS URL ending in `/api`, and configure a rewrite from `/*` to `/index.html`.
6. Verify registration, general and document chat, sources, and deletion on the deployed site. Restart the backend and confirm that a previously uploaded file can still be queried.

## Learning the RAG flow

Think of the vector database as a meaning-based index. The app converts every small document passage into a vector when you upload it. Your question is converted the same way. ChromaDB finds passages close in meaning and returns only the signed-in user's matches. The language model sees those passages and your question, then writes an answer with source labels. The relational database keeps accounts, document metadata, chat messages, and source references. ChromaDB keeps the embeddings on disk.
