# API image. The same image runs the worker, the scheduler, and migrations
# by overriding the command (see docker-compose.prod.yml).
# The image healthcheck calls /live and only fits the default API command.

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/costura ./costura
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS runtime

ARG COSTURA_UID=1001
ARG COSTURA_GID=1001

# The digest-pinned base already ships ca-certificates; apt only upgrades its packages.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${COSTURA_GID}" costura \
    && useradd --uid "${COSTURA_UID}" --gid "${COSTURA_GID}" --home-dir /app --shell /usr/sbin/nologin costura \
    && rm -rf /usr/local/lib/python3.14/site-packages/pip /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14

WORKDIR /app
COPY --from=build --chown=costura:costura /app/.venv /app/.venv
COPY --from=build --chown=costura:costura /app/alembic /app/alembic
COPY --from=build --chown=costura:costura /app/alembic.ini /app/alembic.ini
COPY --chown=costura:costura LICENSE NOTICE /app/licenses/
COPY --chown=costura:costura third_party/licenses/ /app/licenses/third-party/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER costura
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live', timeout=2)"]

# Uvicorn's own proxy headers stay off. COSTURA_TRUSTED_PROXIES is what
# the rate limiter trusts, and it does not authorize development-session writes.
CMD ["uvicorn", "costura.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
