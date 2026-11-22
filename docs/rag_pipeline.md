# RAG pipeline

PyMuPDF extracts text by page. The ingestion service splits text at word boundaries with overlap, embeds it locally with MiniLM, and stores the vectors in persistent ChromaDB. Chunk metadata records the owner, document ID, filename, and page. DOCX and TXT remain supported. Configure `EMBEDDING_PROVIDER` to use existing Ollama or OpenAI embeddings with their corresponding collection.

Groq classifies the latest question using recent turns and the conversation's attachments. ChromaDB searches ready attachments owned by the requester and can find relevant PDFs even when the question omits filenames. General questions without a relevant passage use Groq's general chat. For comparisons, retrieval can return passages per document. Whole-collection summaries sample excerpts across each attached file. The backend validates citation indices and stores them with the conversation in MySQL.

PDF uploads require extractable text. The backend rejects damaged and password-protected PDFs and limits the combined request size, page count, and amount of extracted text.
