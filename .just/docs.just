_root := justfile_directory()

# Rewrite llms.txt from the documentation pages.
llms:
    uv run --project "{{_root}}/apps/api" python "{{_root}}/scripts/build-llms-txt.py"

# Fail when llms.txt is stale (regenerate to a temp file and diff). Run after editing a doc; `just docs::check-llms` is not part of `just check`.
check-llms:
    uv run --project "{{_root}}/apps/api" python "{{_root}}/scripts/build-llms-txt.py" --check
