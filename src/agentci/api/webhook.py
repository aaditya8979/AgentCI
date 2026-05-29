"""
GitHub webhook receiver with HMAC-SHA256 signature verification.

Handles pull_request events (opened, synchronize, reopened),
filters against trigger patterns, and enqueues eval jobs
via Temporal workflow or direct database write.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid

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


async def _extract_changed_files(
    repo: str,
    pr_number: int,
    request: Request,
) -> list[str]:
    """
    Extract changed file paths by calling the GitHub API.

    Uses the GitHub App installation token to fetch the list of files
    changed in a PR, handling pagination (up to 300 files).
    """
    from ..reporter.github import GitHubClient

    try:
        # Get the GitHub client — try to use credentials from env
        gh = GitHubClient()
        headers = await gh._headers()
        client = await gh._get_client()

        files: list[str] = []
        page = 1
        while True:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
                headers=headers,
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            page_files = resp.json()
            if not page_files:
                break
            files.extend(f["filename"] for f in page_files)
            # Stop after 3 pages (300 files) to avoid excessive API calls
            if len(page_files) < 100 or page >= 3:
                break
            page += 1

        await gh.close()
        logger.info("Fetched %d changed files for %s#%d", len(files), repo, pr_number)
        return files

    except Exception as e:
        logger.warning(
            "Could not fetch changed files for %s#%d (proceeding with full eval): %s",
            repo, pr_number, e,
        )
        return []


@router.post("/github", response_model=WebhookResponse, status_code=202)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
):
    """
    Receive and process GitHub webhook events.

    Verifies HMAC-SHA256 signature, processes pull_request events,
    filters against trigger patterns, writes DB row, and starts
    a Temporal workflow for the evaluation.
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

    # ── Rate limiting ─────────────────────────────────────────────────
    redis = getattr(request.app.state, "redis", None)
    if redis:
        try:
            from ..cache.redis_client import check_rate_limit
            max_evals_per_hour = int(os.environ.get("AGENTCI_RATE_LIMIT", "20"))
            allowed = await check_rate_limit(
                repo=repo_full_name,
                limit=max_evals_per_hour,
                window_seconds=3600,
            )
            if not allowed:
                logger.warning("Rate limit exceeded for %s", repo_full_name)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={
                        "action": "rate_limited",
                        "reason": f"Repository {repo_full_name} has exceeded the evaluation "
                                  f"rate limit ({max_evals_per_hour}/hour). Retry later.",
                    },
                    headers={"Retry-After": "3600"},
                )
        except Exception as e:
            logger.warning("Rate limit check failed (proceeding): %s", e)

    # Get changed files via GitHub API
    changed_files = await _extract_changed_files(repo_full_name, pr_number, request)

    # Filter against trigger patterns (default: Python files)
    trigger_patterns = ["**/*.py"]

    if changed_files and not _matches_trigger_patterns(changed_files, trigger_patterns):
        return WebhookResponse(
            action="skipped",
            reason="No trigger files changed",
        )

    # Generate run ID
    run_id = str(uuid.uuid4())

    # ── Write initial DB row ──────────────────────────────────────────
    try:
        from ..db.connection import get_pool
        pool = get_pool()
        from ..db import queries
        await queries.create_eval_run(
            pool,
            repo_full_name=repo_full_name,
            commit_sha=head_sha,
            pr_number=pr_number,
            eval_suite="full",
            triggered_by="webhook",
            metadata={"base_sha": base_sha, "changed_files": changed_files[:50]},
        )
        logger.info("Created eval run %s in database", run_id)
    except Exception as e:
        logger.error("Failed to write eval run to DB: %s", e)
        # Continue — Temporal can still start the workflow

    # ── Start Temporal workflow ───────────────────────────────────────
    temporal_client = getattr(request.app.state, "temporal", None)
    if temporal_client is not None:
        try:
            from ..workflows.eval_workflow import EvalRunWorkflow, EvalRunInput
            task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "agentci-eval")

            workflow_input = EvalRunInput(
                run_id=run_id,
                repo_full_name=repo_full_name,
                commit_sha=head_sha,
                pr_number=pr_number,
                eval_suite="full",
                scenarios_path="./eval/scenarios",
                triggered_by="webhook",
            )

            await temporal_client.start_workflow(
                EvalRunWorkflow.run,
                workflow_input,
                id=f"eval-{run_id}",
                task_queue=task_queue,
            )
            logger.info("Started Temporal workflow eval-%s on queue %s", run_id, task_queue)

        except Exception as e:
            logger.error("Failed to start Temporal workflow: %s", e)
            try:
                await queries.update_eval_run_status(pool, run_id, "failed")
            except Exception as db_err:
                logger.error("Failed to update run status after workflow failure: %s", db_err)
    else:
        logger.warning("Temporal not available — eval run %s is queued but not started", run_id)

    return WebhookResponse(
        action="queued",
        reason=f"Evaluation queued for {repo_full_name}#{pr_number}",
        run_id=run_id,
    )
