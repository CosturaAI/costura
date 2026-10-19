import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from costura import __version__
from costura.api import router as api_router
from costura.api.access import access_middleware
from costura.api.demo_cache import DemoCache, demo_cache_middleware, warm_forever
from costura.api.deps import SettingsDep
from costura.api.ratelimit import rate_limit_middleware
from costura.config import Settings, get_settings, production_warnings, require_production_config
from costura.db import get_engine
from costura.errors import DomainError
from costura.metrics import metrics_response
from costura.telemetry import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Refuse an unsafe production configuration and set up logging when the server starts,
    not when a module imports the app."""
    settings: Settings = app.state.settings
    require_production_config(settings)
    configure_logging()
    for warning in production_warnings(settings):
        logging.getLogger("costura.startup").warning(warning)
    if app.state.demo_cache is None or not settings.costura_demo_warm_url:
        yield
        return
    warming = asyncio.create_task(warm_forever(app, settings.costura_demo_warm_url))
    try:
        yield
    finally:
        warming.cancel()
        with suppress(asyncio.CancelledError):
            await warming


def create_app(settings: Settings | None = None) -> FastAPI:
    """The API application. `settings` defaults to the process settings; passing others makes
    every route, guard and middleware of this app read them (`SettingsDep`)."""
    settings = settings or get_settings()
    app = FastAPI(title="Costura", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.demo_cache = (
        DemoCache(settings.costura_demo_cache_mb * 1024 * 1024)
        if settings.costura_demo_cache_mb
        else None
    )
    if settings is not get_settings():
        app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.costura_web_origin],
        allow_methods=["GET", "PUT", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    app.middleware("http")(demo_cache_middleware)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(access_middleware)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(technical)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    return app


VALIDATION_CODE = "validation_failed"


async def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """The one translation from a domain error to an HTTP response: `detail` is the message,
    `code` names the class in `docs/operations/errors.md`."""
    if not isinstance(exc, DomainError):
        raise exc
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code})


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [{key: value for key, value in error.items() if key != "input"} for error in errors]
    return JSONResponse(
        status_code=422, content={"detail": jsonable_encoder(detail), "code": VALIDATION_CODE}
    )


def _database_reachable() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc


technical = APIRouter()


@technical.get("/live", tags=["technical"])
def live() -> dict[str, str]:
    """Process is up. Does not touch the database. Not a product route."""
    return {"status": "ok"}


@technical.get("/ready", tags=["technical"])
def ready() -> dict[str, str]:
    """Database is reachable. Not a product route."""
    _database_reachable()
    return {"status": "ok", "database": "ok"}


@technical.get("/health", tags=["technical"])
def health(settings: SettingsDep) -> dict[str, str]:
    """Same database check as /ready, plus the environment name and the API release. Not a
    product route."""
    _database_reachable()
    return {
        "status": "ok",
        "env": settings.costura_env,
        "database": "ok",
        "version": __version__,
    }


@technical.get("/metrics", include_in_schema=False)
def metrics() -> PlainTextResponse:
    """HTTP counters for this process and database gauges for the queue and syncs."""
    return metrics_response()


app = create_app()
