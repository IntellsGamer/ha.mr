"""Compatibility export for ASGI worker configurations.

Use ``asgi:app`` with Uvicorn or another ASGI server. This module exists only
for deployments that previously imported ``wsgi:app``; it is not a WSGI app.
"""

from app import app

__all__ = ["app"]
