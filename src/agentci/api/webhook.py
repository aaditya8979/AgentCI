"""
GitHub webhook receiver with HMAC-SHA256 signature verification.

Handles pull_request events (opened, synchronize, reopened),
filters against trigger patterns, and enqueues eval jobs.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from fnmatch import fnmatch
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class WebhookResponse(BaseModel):
    """Standard webhook response."""
    action: str
    reason: str = ""
    run_id: str | None = None


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify the GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes.
        signature: The X-Hub-Signature-256 header value (sha256=...).
        secret: The webhook secret configured in the GitHub App.

    Returns:
        True if the signature is valid.
    """
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def _matches_trigger_patterns(
    changed_files: list[str],
    patterns: list[str],
) -> bool:
    """Check if any changed files match the trigger patterns."""
    from pathlib import PurePath
    for filepath in changed_files:
        p = PurePath(filepath)
        for pattern in patterns:
            if p.match(pattern):
                return True
    return False


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
):
    """
    Receive and process GitHub webhook events.

    Verifies HMAC-SHA256 signature, processes pull_request events,
    filters against trigger patterns, and enqueues eval jobs.
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=500, detail="GITHUB_WEBHOOK_SECRET not configured")

    if not x_hub_signature_256:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")

    if not verify_signature(body, x_hub_signature_256, webhook_secret):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse event
    if x_github_event == "ping":
        return WebhookResponse(action="pong", reason="Webhook configured successfully")

    if x_github_event != "pull_request":
        return WebhookResponse(
            action="ignored",
            reason=f"Unsupported event type: {x_github_event}",
        )

    payload = await request.json()
    action = payload.get("action", "")

    if action not in ("opened", "synchronize", "reopened"):
        return WebhookResponse(
            action="ignored",
            reason=f"Unsupported PR action: {action}",
        )

    # Extract PR metadata
    pr = payload.get("pull_request", {})
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    pr_number = payload.get("number", 0)
    head_sha = pr.get("head", {}).get("sha", "")
    base_sha = pr.get("base", {}).get("sha", "")

    logger.info(
        "PR event: %s/%s #%d (%s) sha=%s",
        repo_full_name, action, pr_number, pr.get("title", ""), head_sha[:7],
    )

    # Get changed files (from the PR payload or a separate API call)
    # For now, we extract from the PR payload if available
    changed_files = _extract_changed_files(payload)

    # Filter against trigger patterns
    # Default patterns if not configured
    trigger_patterns = ["**/*.py"]

    if changed_files and not _matches_trigger_patterns(changed_files, trigger_patterns):
        return WebhookResponse(
            action="skipped",
            reason="No trigger files changed",
        )

    # Enqueue eval job
    run_id = str(uuid.uuid4())

    logger.info(
        "Queued eval run %s for %s#%d @ %s",
        run_id, repo_full_name, pr_number, head_sha[:7],
    )

    # TODO: In Phase 4, this will enqueue a Temporal workflow.
    # For now, we return the run_id for the caller to poll.

    return WebhookResponse(
        action="queued",
        reason=f"Eval run queued for {repo_full_name}#{pr_number}",
        run_id=run_id,
    )


def _extract_changed_files(payload: dict[str, Any]) -> list[str]:
    """Extract changed file paths from the webhook payload."""
    files = []

    # Some webhook payloads include changed files directly
    pr = payload.get("pull_request", {})

    # The files are typically not in the webhook payload itself;
    # they require a separate API call. For now, return empty
    # to allow all events through (the trigger filter becomes a no-op).
    return files
