# Caddy rebuilt with the builder's Go toolchain and a current golang.org/x/net, so the binary
# does not wait on an upstream image rebuild for Go security fixes. Runs as a non-root user.
# The healthcheck uses BusyBox wget from the base image.
FROM --platform=$BUILDPLATFORM caddy:2.11.7-builder-alpine@sha256:aa705b1e8e4bce41a7a30de934c1e00f6821667c1d1206424465065c92cb7674 AS build
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH CGO_ENABLED=0 xcaddy build v2.11.7 --replace golang.org/x/net=golang.org/x/net@v0.61.0 --output /usr/bin/caddy \
    && cd /go/pkg/mod \
    && find . -type f \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'COPYING*' \) \
        -not -path './cache/*' -exec install -D -m 0644 {} /licenses/{} \;

FROM caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f
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
