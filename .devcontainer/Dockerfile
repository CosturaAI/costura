FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04@sha256:d94c97dd9cacf183d0a6fd12a8e87b526e9e928307674ae9c94139139c0c6eae

ARG TARGETARCH
# v2026.10.15
ARG MISE_VERSION=2026.10.15
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x64; sum=e3b186d4c70627f27037be615becaf4acfb30e41fb6a1819486717dc94e4e2a9 ;; \
      arm64) arch=arm64; sum=3abbaac305a465ef038eb4ea07b961c037a8b639108005e43f8e2c00a8f67c11 ;; \
      *) echo "unsupported architecture $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/mise \
      "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/mise-v${MISE_VERSION}-linux-${arch}"; \
    echo "${sum}  /usr/local/bin/mise" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/mise; \
    echo 'eval "$(mise activate bash)"' >> /etc/bash.bashrc; \
    echo 'eval "$(mise activate zsh)"' >> /etc/zsh/zshrc
