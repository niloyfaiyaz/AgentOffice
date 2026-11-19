# Minimal image for executing agent-generated code. Runs with --network none,
# read-only root, a non-root user and CPU/memory/pid limits (see app/tools/sandbox.py).
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.3 && useradd -u 10001 -m runner
USER runner
WORKDIR /workspace
