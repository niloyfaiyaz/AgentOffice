# Minimal image for executing agent-generated code. Runs with --network none,
# read-only root, a non-root user and CPU/memory/pid limits (see app/tools/sandbox.py).
# Pinned by digest (multi-arch index) so a re-tagged upstream image cannot change the sandbox.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
RUN pip install --no-cache-dir pytest==8.3.3 && useradd -u 10001 -m runner
USER runner
WORKDIR /workspace
