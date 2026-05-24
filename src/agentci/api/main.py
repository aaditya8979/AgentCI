"""
FastAPI application for AgentCI.

Provides the webhook endpoint for GitHub PR events and REST API for eval runs.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .webhook import router as webhook_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    logger.info("AgentCI API starting up")
    yield
    logger.info("AgentCI API shutting down")


app = FastAPI(
    title="AgentCI",
    description="Enterprise-Grade CI/CD Quality Gate for LLM Agents",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "agentci"}
