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
COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend
CMD ["sh", "-c", "python -m flask --app run db upgrade && exec gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT:-10000} run:app"]
