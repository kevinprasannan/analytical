# Backend image — FastAPI API + the worker (same image, different command).
# Deps + the analytical_core / app packages are installed from backend/pyproject.toml
# so the image never drifts from the pinned manifest. Alembic migrations and the
# docs/11 gate file are read from the copied source tree at runtime.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Source (context is the repo root — see deploy/docker-compose.yml).
COPY backend/ ./backend/
COPY docs/11-provider-validation.status.yaml ./docs/11-provider-validation.status.yaml
COPY docs/11-PROVIDER-VALIDATION.md ./docs/11-PROVIDER-VALIDATION.md

# Installs the pinned dependencies (incl. httpx) + the two first-party packages.
RUN pip install ./backend

ARG GIT_SHA=""
ENV ANALYTICAL_GIT_SHA=$GIT_SHA

WORKDIR /app/backend
EXPOSE 8000

# Overridden by the worker service; the API is the default.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
