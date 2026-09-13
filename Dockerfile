FROM ghcr.io/astral-sh/uv:python3.14-alpine AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apk add --no-cache gcc musl-dev linux-headers

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-alpine AS runtime

WORKDIR /app

RUN apk add --no-cache rclone tzdata su-exec \
    && mkdir -p /app/rclone /app/downloads /app/log /app/sessions /app/temp \
    && ln -sf /usr/bin/rclone /app/rclone/rclone

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PUID=0 \
    PGID=0

COPY --from=build /app/.venv /app/.venv
COPY src /app/src
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && sed -i 's/\r$//' /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "hermes_telegram_downloader"]
