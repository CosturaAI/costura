# Caddy rebuilt with the builder's Go toolchain and a current golang.org/x/net, so the binary
# does not wait on an upstream image rebuild for Go security fixes. Runs as a non-root user.
# The healthcheck uses BusyBox wget from the base image.
FROM --platform=$BUILDPLATFORM caddy:2.11.7-builder-alpine@sha256:ef9b65adf9a224770c6d5f6d1ae1bf99bc3caaa78d8c4bae3ea949ee6984f301 AS build
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH CGO_ENABLED=0 xcaddy build v2.11.7 --replace golang.org/x/net=golang.org/x/net@v0.61.0 --output /usr/bin/caddy \
    && cd /go/pkg/mod \
    && find . -type f \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'COPYING*' \) \
        -not -path './cache/*' -exec install -D -m 0644 {} /licenses/{} \;

FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
USER root
COPY --from=build /usr/bin/caddy /usr/bin/caddy
COPY --from=build /licenses /usr/share/licenses/caddy
RUN setcap cap_net_bind_service=+ep /usr/bin/caddy \
    && addgroup -g 1001 caddy \
    && adduser -D -H -u 1001 -G caddy -s /sbin/nologin caddy \
    && chown -R caddy:caddy /data /config /etc/caddy
COPY --chown=caddy:caddy Caddyfile /etc/caddy/Caddyfile
USER caddy
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:9080/health"]
