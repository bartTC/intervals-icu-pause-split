"""Exceptions the library raises on purpose; the CLI turns them into an error panel."""

from __future__ import annotations


class PauseSplitError(Exception):
    """Base class for everything this package raises on purpose."""


class IntervalsError(PauseSplitError):
    """intervals.icu could not be reached, or answered with an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthError(IntervalsError):
    """The API key or access token was rejected (HTTP 401 or 403)."""


class NotFoundError(IntervalsError):
    """The activity does not exist, or the credentials cannot see it (HTTP 404)."""


class DataError(PauseSplitError):
    """The activity or a backup cannot be used as asked, e.g. it has no time stream."""
