# claude-and-goose-runtime
#
# Sandboxed image for running Goose recipes against a mounted target repo.
# Host-isolation is structural: the only host paths visible to the runtime
# are whatever is bind-mounted by the wrapper script. See issue #4.

FROM debian:bookworm-slim

ARG TARGETARCH
ARG GOOSE_VERSION=1.35.0
ARG MCP_VERSION=1.0.5

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        libxcb1 \
        libdbus-1-3 \
        libgomp1 \
        tar \
        bzip2 \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Goose CLI — pick the right tarball per arch.
RUN set -eux; \
    case "${TARGETARCH}" in \
        arm64) goose_arch="aarch64-unknown-linux-gnu" ;; \
        amd64) goose_arch="x86_64-unknown-linux-gnu" ;; \
        *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/goose.tar.bz2 \
        "https://github.com/block/goose/releases/download/v${GOOSE_VERSION}/goose-${goose_arch}.tar.bz2"; \
    tar -xjf /tmp/goose.tar.bz2 -C /usr/local/bin --strip-components=1 ./goose; \
    chmod +x /usr/local/bin/goose; \
    rm /tmp/goose.tar.bz2

# github-mcp-server — same per-arch dance.
RUN set -eux; \
    case "${TARGETARCH}" in \
        arm64) mcp_arch="Linux_arm64" ;; \
        amd64) mcp_arch="Linux_x86_64" ;; \
        *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/mcp.tar.gz \
        "https://github.com/github/github-mcp-server/releases/download/v${MCP_VERSION}/github-mcp-server_${mcp_arch}.tar.gz"; \
    tar -xzf /tmp/mcp.tar.gz -C /usr/local/bin github-mcp-server; \
    chmod +x /usr/local/bin/github-mcp-server; \
    rm /tmp/mcp.tar.gz

# Non-root runtime user. HOME is ephemeral — discarded with --rm.
RUN useradd --create-home --uid 1000 --shell /bin/bash goose

USER goose
WORKDIR /work
ENV HOME=/home/goose

# No ENTRYPOINT — the wrapper passes the full `goose run ...` command.
# This keeps the image usable for the smoke test (`bash -c '...'`) too.
CMD ["goose", "--help"]
