# The whole lab in one container: the built UI, the API, and the worker that runs forks and blames.
# Deploy notes: DEPLOY.md.

FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY datasets ./datasets
COPY examples ./examples
COPY deploy ./deploy
COPY --from=ui /ui/dist ./ui/dist

# Hosted mode: reading and replay are open; forks and blames need the demo key (hosting.py).
ENV AGENTLAB_PUBLIC=1 \
    PYTHONUNBUFFERED=1 \
    AGENTLAB_DB=/data/lab.db \
    PORT=8000
EXPOSE 8000
CMD ["sh", "deploy/start.sh"]
