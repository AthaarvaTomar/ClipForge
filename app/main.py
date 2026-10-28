import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.api.v1.endpoints.websocket import router as ws_router
from app.config import settings
from app.core.logging import logger, setup_logging
from app.core.security import verify_api_key
from app.services.planner_service import (
    TimelinePlanNotFoundError,
    TimelinePlanValidationError,
)
from app.services.timeline_engine import TimelineOperationError
from app.services.timeline_service import (
    TimelineNotFoundError,
    TimelineVersionConflictError,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Setup structured logging
    setup_logging()
    logger.info("Initializing %s application services", settings.PROJECT_NAME)

    # Ensure local storage directories exist
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Shutting down %s application", settings.PROJECT_NAME)


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware with configurable origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Track request processing duration and log incoming HTTP requests."""
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    logger.info(
        "%s %s - %s - %.2fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    return response


# Standardized error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    try:
        status_name = HTTPStatus(exc.status_code).name
    except ValueError:
        status_name = "HTTP_ERROR"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error": {
                "code": status_name,
                "message": str(exc.detail),
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    serialized_errors = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": serialized_errors,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters",
                "details": serialized_errors,
            },
        },
    )


@app.exception_handler(TimelineVersionConflictError)
async def timeline_conflict_handler(
    request: Request,
    exc: TimelineVersionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "current_version": exc.current_version,
            "expected_version": exc.expected_version,
            "error": {
                "code": "CONFLICT",
                "message": str(exc),
                "current_version": exc.current_version,
                "expected_version": exc.expected_version,
            },
        },
    )


@app.exception_handler(TimelineNotFoundError)
async def timeline_not_found_handler(
    request: Request,
    exc: TimelineNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": str(exc),
            "error": {
                "code": "NOT_FOUND",
                "message": str(exc),
            },
        },
    )


@app.exception_handler(TimelineOperationError)
async def timeline_operation_error_handler(
    request: Request,
    exc: TimelineOperationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": str(exc),
            "error": {
                "code": "UNPROCESSABLE_ENTITY",
                "message": str(exc),
            },
        },
    )


@app.exception_handler(TimelinePlanNotFoundError)
async def timeline_plan_not_found_handler(
    request: Request,
    exc: TimelinePlanNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": str(exc),
            "error": {
                "code": "NOT_FOUND",
                "message": str(exc),
            },
        },
    )


@app.exception_handler(TimelinePlanValidationError)
async def timeline_plan_validation_error_handler(
    request: Request,
    exc: TimelinePlanValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": str(exc),
            "error": {
                "code": "UNPROCESSABLE_ENTITY",
                "message": str(exc),
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server exception: %s", exc)
    err_msg = str(exc) if settings.DEBUG else "Internal server error"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": err_msg,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": err_msg,
            },
        },
    )


# Include v1 API router protected with optional API key
app.include_router(
    api_router,
    prefix=settings.API_V1_PREFIX,
    dependencies=[Depends(verify_api_key)],
)

# Include WebSocket router for live events
app.include_router(ws_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    return {"message": f"Welcome to {settings.PROJECT_NAME} API. Visit /docs for documentation."}
