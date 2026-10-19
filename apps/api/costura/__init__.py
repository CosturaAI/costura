"""Costura API package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("costura-api")
except PackageNotFoundError:
    # Editable/source checkouts without an installed distribution.
    __version__ = "0.0.0"
