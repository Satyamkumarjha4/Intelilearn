# Local development image for the Django API and the Celery worker.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
# Node runs the sandbox scripts (static and security checks, later the headless render check); bun installs their packages.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=oven/bun:1.3 /usr/local/bin/bun /usr/local/bin/bun

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code edits don't invalidate this layer.
# The venv lives in /opt/venv, outside the /app bind mount used by docker compose.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# The sandbox package comes from the `sandbox` build context (see docker-compose.yml). Its node_modules live in the
# image and are kept visible under the bind mount by an anonymous volume, like the frontend's.
COPY --from=sandbox package.json bun.lock /sandbox/
RUN cd /sandbox && bun install --frozen-lockfile

COPY . .

EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]
