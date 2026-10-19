# Next.js standalone server. next.config.ts sets output: "standalone".

FROM node:26.11.1-bookworm-slim@sha256:86f07bc9c5dce4578cf37e5a418b7bfc7f817cda25cde66e2b66e95ed86c4567 AS base
ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1
# Node 26 ships without Corepack; install the pinned pnpm with npm.
RUN npm install --global pnpm@12.10.1

FROM base AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
RUN pnpm build \
    && node scripts/collect-licenses.mjs /app/npm-THIRD-PARTY.txt

FROM node:26.11.1-bookworm-slim@sha256:86f07bc9c5dce4578cf37e5a418b7bfc7f817cda25cde66e2b66e95ed86c4567 AS runtime

ARG COSTURA_UID=1001
ARG COSTURA_GID=1001
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
        /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
    && groupadd --gid "${COSTURA_GID}" nodejs \
    && useradd --uid "${COSTURA_UID}" --gid "${COSTURA_GID}" --home-dir /app --shell /usr/sbin/nologin nextjs
COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --chown=nextjs:nodejs LICENSE NOTICE /app/licenses/
COPY --chown=nextjs:nodejs third_party/licenses/ /app/licenses/third-party/
COPY --from=build --chown=nextjs:nodejs /app/npm-THIRD-PARTY.txt /app/licenses/third-party/
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then((r)=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
