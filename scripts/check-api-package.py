"""Assert the built wheel installs as a real package.

Runs inside the throwaway environment created by `just api::package-check`, so it imports the
installed distribution rather than the source tree.
"""

import sys
from importlib.metadata import version
from pathlib import Path

import costura


def main() -> None:
    path = Path(costura.__file__).resolve()
    assert "site-packages" in path.parts, path

    installed = version("costura-api")
    assert costura.__version__ == installed, (costura.__version__, installed)

    legal = path.parent / "legal"
    required = (
        "LICENSE",
        "NOTICE",
        "shadcn-MIT.txt",
        "lucide-ISC.txt",
        "fonts-OFL-1.1.txt",
        "psycopg-LGPL-3.0.txt",
        "psycopg-GPL-3.0.txt",
    )
    missing = [name for name in required if not (legal / name).is_file()]
    assert not missing, missing
    print(f"installed costura {installed} from {path}")


if __name__ == "__main__":
    sys.exit(main())
