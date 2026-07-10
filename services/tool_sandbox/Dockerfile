# The digest is shared with the main image and intentionally kept in sync by
# the supply-chain review workflow.
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

# git backs the workspace-local git workflows the bash tool advertises.
# Deliberately no compilers/build tooling: the executor promises scripts,
# git, and Python — not native builds (see BUILTIN_TOOL_DESCRIPTIONS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 65532 sandbox \
    && adduser --system --uid 65532 --ingroup sandbox --home /workspace sandbox \
    && mkdir -p /srv /workspace /run/odysseus-sandbox \
    && chown -R sandbox:sandbox /srv /workspace

COPY services/tool_sandbox/server.py /srv/server.py

WORKDIR /workspace
# Compose starts as root only to create the root-owned Unix socket, then
# server.py drops to UID/GID 65532 before accepting requests or spawning code.
CMD ["python", "/srv/server.py"]
