# ---- build the dashboard -------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- backend runtime ------------------------------------------------------
FROM python:3.12-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt \
 && python -m playwright install --with-deps chromium
COPY backend/ ./backend/
COPY prompts/ ./prompts/
COPY fake-job-site/ ./fake-job-site/
COPY scripts/ ./scripts/
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/data
ENV API_HOST=0.0.0.0 API_PORT=8000 BROWSER_HEADLESS=true DATABASE_URL=sqlite:////app/data/job_agent.db
EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
