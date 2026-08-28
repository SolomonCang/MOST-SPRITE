from __future__ import annotations

import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from most_sprite.api.routes import router
from most_sprite.api.runtime import Runtime
from most_sprite.auth.accounts import ensure_preconfigured_accounts
from most_sprite.auth.routes import router as auth_router
from most_sprite.config import get_settings
from most_sprite.configuration import ensure_default_config
from most_sprite.db.session import dispose_database, init_database, session_scope
from most_sprite.domain.schemas import ErrorEnvelope
from most_sprite.errors import SpriteError
from most_sprite.logging import configure_logging

REQUEST_COUNT = Counter(
    "sprite_api_requests_total", "API request count", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram("sprite_api_request_seconds", "API request latency", ["method", "path"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.prepare_runtime()
    await init_database()
    async with session_scope() as session:
        await ensure_preconfigured_accounts(session)
        await ensure_default_config(session)
    runtime = Runtime.build()
    app.state.runtime = runtime
    await runtime.start()
    yield
    await runtime.stop()
    await dispose_database()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="MOST-SPRITE API",
        version=settings.software_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_and_metrics(request: Request, call_next):  # noqa: ANN001
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - started
        route_path = getattr(request.scope.get("route"), "path", request.url.path)
        REQUEST_COUNT.labels(request.method, route_path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, route_path).observe(duration)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(SpriteError)
    async def sprite_error_handler(request: Request, exc: SpriteError) -> JSONResponse:
        envelope = ErrorEnvelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            correlation_id=getattr(request.state, "correlation_id", str(uuid4())),
            retryable=exc.retryable,
        )
        return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        envelope = ErrorEnvelope(
            code="REQUEST_VALIDATION_FAILED",
            message="request does not satisfy the API contract",
            details={"errors": exc.errors()},
            correlation_id=getattr(request.state, "correlation_id", str(uuid4())),
            retryable=False,
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(auth_router)
    app.include_router(router)
    return app


app = create_app()
