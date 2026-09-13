#!/bin/sh
set -e

PUID="${PUID:-0}"
PGID="${PGID:-0}"

mkdir -p /app/downloads /app/log /app/sessions /app/temp

if [ "$PUID" = "0" ]; then
  exec "$@"
fi

if ! getent group "$PGID" >/dev/null 2>&1; then
  addgroup -g "$PGID" hermes
fi

GROUP_NAME="$(getent group "$PGID" | cut -d: -f1)"

if ! getent passwd "$PUID" >/dev/null 2>&1; then
  adduser -D -H -s /sbin/nologin -u "$PUID" -G "$GROUP_NAME" hermes
fi

chown "$PUID:$PGID" /app/downloads /app/log /app/sessions /app/temp
[ -e /app/data.yaml ] && chown "$PUID:$PGID" /app/data.yaml || true
[ -e /app/bot.yaml ] && chown "$PUID:$PGID" /app/bot.yaml || true
[ -e /app/config.yaml ] && chown "$PUID:$PGID" /app/config.yaml || true

exec su-exec "$PUID:$PGID" "$@"
