FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.6 AS uv

FROM python:3.12-slim-bookworm AS backend
WORKDIR /srv/keitaro/backend
COPY --from=uv /uv /bin/uv
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-cache --no-python-downloads

FROM python:3.12-slim-bookworm
ENV PATH="/srv/keitaro/backend/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/keitaro/backend
COPY --from=backend /srv/keitaro/backend/.venv ./.venv
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY --from=frontend /build/dist /srv/keitaro/frontend/dist
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
