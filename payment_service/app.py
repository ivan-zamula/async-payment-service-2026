"""Build the FastAPI application and register its routes."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from payment_service.controllers.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Payment processing service")
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(NotImplementedError)
    async def not_implemented(request: Request, error: NotImplementedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={"detail": "Payment handler is not implemented yet"},
        )

    return app
