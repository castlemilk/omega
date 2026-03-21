# Dockerfile — omega-nodes (Python heartbeat loop)
FROM python:3.11-slim

WORKDIR /app

# Install the package (stdlib-only deps, no external packages needed)
COPY pyproject.toml ./
COPY omega/ ./omega/

RUN pip install --no-cache-dir -e .

# Shared data volume mount point
RUN mkdir -p /data

CMD ["python3", "-m", "omega.examples.vectora_main"]
