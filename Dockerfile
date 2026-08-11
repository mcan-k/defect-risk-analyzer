# =============================================================================
# Predictive Defect Analysis Engine — Docker Image
# =============================================================================
# Single image serving both FastAPI backend and Streamlit frontend.
# Services are orchestrated via docker-compose.yml.
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

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

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
