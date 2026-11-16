# One container with the API, which also serves the compiled page (used by Render; works on any
# Docker host). Files with real data (.env, .pkl, maps) are NOT in the image: they arrive at runtime
# (on Render, as environment variables and Secret Files; see deploy/render/README.md).

# 1) compiled page
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) API
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# dependencies first, so they stay cached while requirements.txt does not change;
# the "-e ." line of requirements.txt needs pyproject.toml and the statement package
COPY requirements.txt pyproject.toml ./
COPY extraction/ extraction/
RUN pip install -r requirements.txt

COPY . .
COPY --from=frontend /build/frontend/dist frontend/dist

# non-root user; it owns /app because the retraining writes a new .pkl in ml/modelos
RUN useradd --create-home --uid 1000 app \
    && mkdir -p data/private ml/modelos ml/dados \
    && chown -R app:app /app
USER app

EXPOSE 10000
CMD ["sh", "deploy/render/start.sh"]
