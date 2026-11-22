# REST API

Protected routes require `Authorization: Bearer <access_token>`. JSON errors have an `error` string; successful resources are JSON. All IDs are scoped to the signed-in account.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create account / issue access token |
| POST / GET | `/api/auth/logout`, `/api/auth/me` | Logout hint / current account |
| POST / GET | `/api/documents` | Multipart `files` upload / list with q, type, status filters |
| GET / DELETE | `/api/documents/<id>` | Read / remove owned document |
| POST | `/api/documents/<id>/reprocess` | Re-run extraction and indexing |
| POST / GET | `/api/chat/conversations` | Create / list conversations |
| GET / PATCH / DELETE | `/api/chat/conversations/<id>` | Read, rename, or delete owned conversation |
| POST | `/api/chat/conversations/<id>/messages` | Ask question and save both messages |
| POST | `/api/ai/ask`, `/api/ai/summarize` | One-off answer / summarize `{document_id, detailed}` |
| POST | `/api/chat/conversations/:id/attachments` | Upload one or more PDFs with multipart `files` |
| PUT / DELETE | `/api/chat/conversations/:id/attachments/:document_id` | Attach a PDF already in the library or detach it from this conversation |
| GET | `/api/documents/:id/pdf` | Open an owned PDF with JWT authorization |
| GET / POST | `/api/search/documents`, `/api/search/semantic` | Document search / semantic query |
| GET | `/api/dashboard/summary` | User-scoped dashboard counts and recent items |
| GET | `/api/health` | Health check |

Register accepts `{name,email,password}`. A question accepts `{question}`. Semantic search accepts `{query}`. Upload size is limited to 16 MiB per HTTP request, and only PDF, DOCX and TXT extensions are accepted.

The conversation detail response includes an `attachments` array. Chat-message retrieval searches only that conversation's attachments. The one-off `/api/ai/ask` endpoint can still search the user's library. Each chat supports up to ten PDFs.
