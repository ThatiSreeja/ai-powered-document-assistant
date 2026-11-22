FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --include=dev
COPY frontend/ ./
RUN VITE_API_URL=/api npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV EMBEDDING_BUNDLED_CACHE=/opt/paperwise/models
RUN python -c "import os; from pathlib import Path; from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; model = ONNXMiniLM_L6_V2(); model.DOWNLOAD_PATH = Path(os.environ['EMBEDDING_BUNDLED_CACHE']) / model.MODEL_NAME; model(['warm up']); (model.DOWNLOAD_PATH / 'onnx.tar.gz').unlink(missing_ok=True)"
COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend
CMD ["sh", "-c", "python -m flask --app run db upgrade && exec gunicorn --config gunicorn.conf.py --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT:-10000} run:app"]
