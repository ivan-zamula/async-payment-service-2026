"""Request-scoped dependencies for HTTP handlers."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # Closing a session also rolls back any uncommitted transaction.
    # The application use case will explicitly choose when to commit.
    async with request.app.state.session_factory() as session:
        yield session
