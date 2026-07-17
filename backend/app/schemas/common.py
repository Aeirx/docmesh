"""Cross-cutting API schemas."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Uniform error body for every non-2xx response.

    ``code`` is a stable machine-readable string the frontend switches on;
    ``request_id`` lets a user-visible error be correlated with server logs.
    """

    detail: str
    code: str
    request_id: str | None = None


class Page(BaseModel, Generic[T]):
    """Offset-paged collection envelope."""

    items: list[T]
    total: int
    offset: int
    limit: int
