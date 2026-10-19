_web := justfile_directory() / "apps" / "web"
# mcr.microsoft.com/playwright:v1.64.0-jammy, matching the @playwright/test version pinned in apps/web/package.json.
_playwright_image := "mcr.microsoft.com/playwright@sha256:c064e7f355d2dda32f669801a1b09e86a1e9252395c844d2cfbbe5c44acb9b79"

# Install web dependencies from the lockfile.
setup:
    cd "{{_web}}" && pnpm install --frozen-lockfile

# Run Next.js with hot reload on http://127.0.0.1:3000.
dev:
    cd "{{_web}}" && pnpm exec next dev --hostname 127.0.0.1 --port 3000

# Production build (next build).
build:
    cd "{{_web}}" && pnpm build

# Lint with ESLint, then reject raw palette classes outside themes and ui.
lint:
    cd "{{_web}}" && pnpm lint

# Check formatting with Prettier.
format-check:
    cd "{{_web}}" && pnpm format:check

# Regenerate the OpenAPI types and fail when that rewrite changes the file.
api-types-check:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_web}}"
    copy="$(mktemp)"
    trap 'rm -f "$copy"' EXIT
    cp src/lib/api/generated.ts "$copy"
    pnpm api:types
    pnpm exec prettier --write src/lib/api/generated.ts >/dev/null
    diff -q "$copy" src/lib/api/generated.ts

# Type check with tsc (runs next typegen first).
typecheck:
    cd "{{_web}}" && pnpm typecheck

# Fix formatting with Prettier.
fix:
    cd "{{_web}}" && pnpm format

# Run Vitest once (unit and render tests).
test *args:
    cd "{{_web}}" && pnpm test {{args}}

# Run Vitest with V8 coverage; fails under the floors in vitest.config.mts.
coverage *args:
    cd "{{_web}}" && pnpm test --coverage {{args}}

# Fail when lines changed since `base` are under 90% covered; run `just web::coverage` first.
diff-coverage base="origin/main":
    cd "{{_web}}" && uv run --project ../api diff-cover coverage/lcov.info --compare-branch={{base}} --fail-under=90

# Capture the product screens of docs/product/screens.md from a running stack (`just dev`).
screens base="http://127.0.0.1:3000":
    cd "{{_web}}" && pnpm test:e2e:install && node e2e/capture-screens.mjs {{base}}

# Build the production app and run Playwright in Chromium.
test-e2e *args:
    cd "{{_web}}" && pnpm build && pnpm test:e2e:install && pnpm test:e2e {{args}}

# COSTURA_WEB_PREBUILT=1 reuses an existing `.next/standalone` build instead of building.
# Build on the host, then run the Playwright suite inside the pinned Playwright image, the same
# Linux Chromium that writes the committed screenshots. CI runs this recipe.
test-e2e-docker *args:
    cd "{{_web}}" && { [ -n "${COSTURA_WEB_PREBUILT:-}" ] || pnpm build; }
    docker run --rm \
        -v "{{justfile_directory()}}:/work" -w /work/apps/web \
        -e HOME=/tmp -e CI -e COSTURA_ENV -e COSTURA_WEB_ORIGIN \
        {{_playwright_image}} \
        bash -c "corepack enable && npx playwright test {{args}}"

# COSTURA_WEB_PREBUILT=1 reuses an existing `.next/standalone` build instead of building.
# Sample organization suite with the browser inside the pinned Playwright image. CI runs this.
test-e2e-demo-docker *args:
    cd "{{_web}}" && { [ -n "${COSTURA_WEB_PREBUILT:-}" ] || pnpm build; }
    COSTURA_PLAYWRIGHT_DOCKER_IMAGE="{{_playwright_image}}" \
        bash "{{justfile_directory()}}/scripts/demo-e2e.sh" {{args}}

# Sample organization suite against PostgreSQL, the API and a seeded sample (needs Docker).
# Pass `--update-snapshots` to replace its snapshots.
test-e2e-demo *args:
    cd "{{_web}}" && pnpm build && pnpm test:e2e:install
    bash "{{justfile_directory()}}/scripts/demo-e2e.sh" {{args}}

# Update or check the Linux Chromium layout snapshots. Pass `--update-snapshots` to replace them.
test-visual *args:
    cd "{{_web}}" && pnpm build && pnpm test:e2e:install && pnpm test:e2e e2e/visual.spec.ts {{args}}

# Regenerate every committed Playwright screenshot (visual.spec.ts and e2e-demo/demo.spec.ts)
# using the official Playwright Docker image, so the Linux Chromium pixels match CI regardless
# of the host OS. Needs Docker; the demo half also needs just, uv and pnpm on the host.
snapshots:
    cd "{{_web}}" && pnpm build
    docker run --rm \
        -v "{{justfile_directory()}}:/work" -w /work/apps/web \
        -e HOME=/tmp \
        {{_playwright_image}} \
        bash -c "corepack enable && npx playwright test e2e/visual.spec.ts --update-snapshots=all"
    cd "{{_web}}" && pnpm build
    COSTURA_PLAYWRIGHT_DOCKER_IMAGE="{{_playwright_image}}" \
        bash "{{justfile_directory()}}/scripts/demo-e2e.sh" --update-snapshots=all
