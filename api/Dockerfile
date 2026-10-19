# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml ./
COPY app ./app
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system nexus && useradd --system --gid nexus --home /app nexus
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
COPY --chown=nexus:nexus alembic.ini ./
COPY --chown=nexus:nexus migrations ./migrations
USER nexus
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
# Migrations run separately (see the `migrate` service in docker-compose.yml) with the
# owner role; the API process only ever holds the non-owner credentials.
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
