"""Build the FastAPI application and register its routes."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from payment_service.application.errors import IdempotencyConflictError, PaymentNotFoundError
from payment_service.controllers.routes import router
from payment_service.infrastructure.database import connect_database, get_database_url


def create_app() -> FastAPI:
    api_key = os.environ.get("API_KEY", "")
    if not api_key.strip():
        raise RuntimeError("Set a non-empty API_KEY environment variable")

    database_url = get_database_url()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with connect_database(database_url) as session_factory:
            app.state.session_factory = session_factory
            yield

    app = FastAPI(title="Payment processing service", lifespan=lifespan)
    app.state.api_key = SecretStr(api_key)
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(PaymentNotFoundError)
    async def payment_not_found(request: Request, error: PaymentNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Payment not found"},
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(request: Request, error: IdempotencyConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Idempotency key already used for a different payment"},
        )

    return app
