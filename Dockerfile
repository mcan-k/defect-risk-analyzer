# =============================================================================
# Predictive Defect Analysis Engine — Docker Image
# =============================================================================
# Single image serving the Streamlit dashboard and the optional FastAPI
# webhook service. Services are orchestrated via docker-compose.yml.
# =============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by chromadb (SQLite, build tools)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies.
#
# The webhook extra is installed by default: one image serves both the
# dashboard and the optional API service, and docker-compose gates the API
# behind a profile rather than behind a separate build. Without it the API
# container would fail at startup with ImportError on fastapi, and the only
# trace would be in the container log.
#
# Build a dashboard-only image with:  docker build --build-arg INSTALL_WEBHOOK=false .
ARG INSTALL_WEBHOOK=true

COPY requirements.txt requirements-webhook.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    if [ "$INSTALL_WEBHOOK" = "true" ]; then \
        pip install --no-cache-dir -r requirements-webhook.txt; \
    fi

# Copy application code
COPY . .

# Install the package itself in editable mode.
# --no-deps: runtime dependencies were already installed above, and
# pyproject.toml reads them dynamically from the same requirements.txt.
RUN pip install --no-cache-dir -e . --no-deps

# Create data directory for runtime files
RUN mkdir -p /app/data

# Default: start the FastAPI backend
# Override in docker-compose.yml for the Streamlit service
EXPOSE 8000
CMD ["uvicorn", "defect_risk_analyzer.api:app", "--host", "0.0.0.0", "--port", "8000"]
