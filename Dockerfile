FROM ghcr.io/astral-sh/uv:python3.14-alpine AS build

WORKDIR /app

# Build deps for packages that need compilation
RUN apk add --no-cache --virtual .build-deps gcc musl-dev

# Install python deps (locked) — layer cached until lockfile changes
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project --no-dev

# Install project itself (editable, so bind-mount source override still works)
COPY src ./src
RUN uv sync --locked --no-dev

# Install rclone (runtime binary)
RUN apk add --no-cache rclone


FROM python:3.14-alpine AS runtime

WORKDIR /app

# Copy venv and rclone from build stage
COPY --from=build /app/.venv /app/.venv
COPY --from=build /usr/bin/rclone /app/rclone/rclone

# Copy app source (editable install points here; compose bind mounts override)
COPY src /app/src

CMD ["/app/.venv/bin/python", "-m", "hermes_telegram_downloader"]
