# Multi-stage image for the AiraCare Foundry Care Orchestrator (A2A hosted agent).
#
# Stage 1 builds an isolated virtualenv with the package + selected extras; stage 2 is a
# slim, non-root runtime that copies only the venv and the package. The container serves the
# frozen A2A contract (airacare.report / airacare.fetch_policy) plus GET /healthz.
#
#   docker build -t airacare-foundry:latest .
#   docker build -t airacare-foundry:agents --build-arg EXTRAS=cosmos,agents,search .
#   docker run --rm -p 8971:8971 -e AIRACARE_A2A_TOKEN=secret airacare-foundry:latest

# ---- Stage 1: builder --------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Which optional-dependency extras to install into the image (see pyproject.toml).
ARG EXTRAS=cosmos

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only what the wheel needs (pyproject targets airacare_foundry) for cache-friendly builds.
COPY pyproject.toml README.md ./
COPY airacare_foundry ./airacare_foundry
RUN pip install ".[${EXTRAS}]"

# ---- Stage 2: runtime --------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AIRACARE_CONFIG=/app/config.container.yaml

# Non-root runtime user.
RUN useradd --create-home --uid 10001 airacare
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY airacare_foundry ./airacare_foundry
COPY config.container.yaml ./config.container.yaml

USER airacare
EXPOSE 8971

# Liveness/readiness probe against the unauthenticated health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8971/healthz',timeout=4).status==200 else 1)"

# --host 0.0.0.0 is set in config.container.yaml; override the config by mounting another file
# and setting AIRACARE_CONFIG, or pass flags after the module name.
CMD ["sh", "-c", "python -m airacare_foundry.a2a_server --config \"$AIRACARE_CONFIG\""]
