"""Static API-key authentication for payment routes."""

from secrets import compare_digest
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    expected_key = request.app.state.api_key.get_secret_value()
    if api_key is None or not compare_digest(
        api_key.encode("utf-8"), expected_key.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
