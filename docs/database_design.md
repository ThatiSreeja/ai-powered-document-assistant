# Database design

`users` stores account identity and a Werkzeug password hash. `documents` stores ownership, sanitized display name, generated storage key, file type, size, processing status and timestamps. `conversations` belongs to a user, and `messages` belongs to a conversation with role, body, sources JSON and timestamp. `document_processing_logs` records ingestion outcome and stage. Foreign keys cascade deletions. Indexes cover emails, ownership, status, and conversation/document relations. Embeddings and passage text live in ChromaDB, not MySQL.

Create the MySQL database with `database/schema.sql`; apply the checked-in initial migration with `flask --app run db upgrade` from `backend/`. For future model changes, generate a migration with `flask --app run db migrate -m "describe change"`, review it, then run `flask --app run db upgrade`.
