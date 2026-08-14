"""WSGI entry point for production servers such as Gunicorn or uWSGI."""

from app import app

__all__ = ["app"]
