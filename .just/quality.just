_root := justfile_directory()

# Scan tracked and untracked source files for secrets (betterleaks).
secrets:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v betterleaks >/dev/null || {
      echo "error: betterleaks is not installed; run: mise install"
      exit 1
    }
    cd "{{_root}}"
    paths=()
    while IFS= read -r -d '' path; do
      [[ -f "$path" ]] && paths+=("$path")
    done < <(git ls-files --cached --others --exclude-standard -z)
    [[ ${#paths[@]} -eq 0 ]] && exit 0
    betterleaks --no-banner --redact dir "${paths[@]}"

# Scan every commit of the git history, as the CI "Secret scan of the git history" job does.
secrets-history:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v betterleaks >/dev/null || {
      echo "error: betterleaks is not installed; run: mise install"
      exit 1
    }
    cd "{{_root}}"
    betterleaks --no-banner --redact git .

# Lint the GitHub Actions workflows (actionlint); `just check` runs it in CI.
workflows:
    cd "{{_root}}" && actionlint -shellcheck= -pyflakes=

# Scan the checkout for fixed high and critical vulnerabilities, as the CI "Security scan" job does.
vulnerabilities:
    cd "{{_root}}" && trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 .

# Run all required quality checks for API and web code.
check:
    just quality::workflows
    just api::lint
    just api::format-check
    just api::typecheck
    just web::lint
    just web::format-check
    just web::typecheck
    just web::api-types-check
    just quality::secrets

# Run pre-commit against all files.
pre-commit:
    cd "{{_root}}" && uv run --project apps/api pre-commit run --all-files
