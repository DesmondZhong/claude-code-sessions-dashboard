# Real-server image — for deploying your own Claude Sessions Dashboard.
# Build context is the repo root.
#
#   docker build -t claude-dashboard .
#   docker run -p 5050:5050 -v claude-data:/data \
#     -e CLAUDE_DASHBOARD_API_KEY=your-secret claude-dashboard
#
# The demo has its own Dockerfile at demo/Dockerfile (re-seeds on startup).

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt gunicorn

# Copy server code and a default config (env vars override these values)
COPY server/app.py /app/server/app.py
COPY server/server-config.yaml /app/server/server-config.yaml

# Persist DB and raw JSONL backups under /data — mount a volume / disk here.
ENV CLAUDE_DASHBOARD_DB_PATH=/data/sessions.db
ENV CLAUDE_DASHBOARD_BACKUP_DIR=/data/backups

CMD ["sh", "-c", "mkdir -p /data/backups && exec gunicorn --chdir /app/server --bind 0.0.0.0:${PORT:-5050} --workers 2 --access-logfile - app:app"]
