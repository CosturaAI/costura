"""HTTP API under `/api/v1`. There is one source of numbers, `costura.spend`; routes only
validate, authorize and serialize. Write routes are guarded by `costura.api.guard`.
`tests/test_architecture.py` checks the layering.
"""

from costura.api.routes import router

__all__ = ["router"]
