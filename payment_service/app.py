"""Build the FastAPI application and register its routes."""

import os

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from payment_service.controllers.routes import router


def create_app() -> FastAPI:
    api_key = os.environ.get("API_KEY", "")
    if not api_key.strip():
        raise RuntimeError("Set a non-empty API_KEY environment variable")

    app = FastAPI(title="Payment processing service")
    app.state.api_key = SecretStr(api_key)
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(NotImplementedError)
    async def not_implemented(request: Request, error: NotImplementedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={"detail": "Payment handler is not implemented yet"},
        )

    return app
