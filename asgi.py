"""ASGI server entry point.

Run locally with: uvicorn asgi:app --host 0.0.0.0 --port 5000
"""

from app import app

__all__ = ["app"]
