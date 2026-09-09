"""Shared FastAPI dependencies."""

from fastapi import Request

from .ntopng import NtopngClient


def get_client(request: Request) -> NtopngClient:
    """The single long-lived ntopng client created during app startup."""
    return request.app.state.ntopng
