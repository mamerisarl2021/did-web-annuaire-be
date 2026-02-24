ARG PYTHON_VERSION=3.14-slim-bookworm

# ════════════════════════════════════════════════════════════════════════
#  Stage 1: Builder — install Python dependencies
# ════════════════════════════════════════════════════════════════════════
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
ENV VIRTUAL_ENV=/opt/venv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# Install dependencies with layer caching
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ════════════════════════════════════════════════════════════════════════
#  Stage 2: Runner — minimal production image
# ════════════════════════════════════════════════════════════════════════
FROM python:${PYTHON_VERSION} AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    bash \
    curl \
    ca-certificates \
    wget \
    gnupg \
    && wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" | tee /etc/apt/sources.list.d/adoptium.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends temurin-21-jre \
    && apt-get remove -y wget gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN java -version

RUN useradd -m -r appuser && \
    mkdir -p /app/staticfiles /app/mediafiles /app/data/dids /app/bin && \
    chown -R appuser:appuser /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV=/opt/venv

WORKDIR /app

COPY --from=builder /app/pyproject.toml /app/uv.lock ./

COPY --chown=appuser:appuser src /app/src

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

COPY --chown=appuser:appuser artifacts/ecdsa-extractor.jar /app/bin/

USER appuser

EXPOSE 8899

CMD ["/app/entrypoint.sh"]