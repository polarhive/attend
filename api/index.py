"""Vercel serverless entrypoint: re-exports the FastAPI app from main."""

from __future__ import annotations

from main import app

__all__ = ["app"]
