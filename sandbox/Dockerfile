# Minimal image for executing agent-generated code. Runs with --network none,
# read-only root, a non-root user and CPU/memory/pid limits (see app/tools/sandbox.py).
# Pinned by digest (multi-arch index) so a re-tagged upstream image cannot change the sandbox.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN pip install --no-cache-dir pytest==8.3.3 && useradd -u 10001 -m runner
USER runner
WORKDIR /workspace
