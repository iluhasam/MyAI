"""REST API transport (FastAPI).

A thin HTTP channel over the exact same Gateway/Router/Agent stack used by the
CLI and Telegram adapters — proving once more that the cognitive core is
transport-agnostic. FastAPI/uvicorn are optional dependencies; import this
package only when actually serving the API.
"""

from __future__ import annotations

from app.api.app import create_api

__all__ = ["create_api"]
