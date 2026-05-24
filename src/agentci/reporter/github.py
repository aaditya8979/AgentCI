"""
GitHub API client for AgentCI.

Handles GitHub App authentication (JWT + installation tokens) and provides
methods for Check Runs, PR comments, and commit status updates.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
import jwt

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubAuthError(Exception):
    """Raised when GitHub App authentication fails."""


class GitHubClient:
    """
    Async GitHub API client authenticated as a GitHub App.

    Uses JWT for app-level auth and installation tokens for
    repository-level operations.
    """

    def __init__(
        self,
        app_id: str | None = None,
        private_key: str | None = None,
        installation_id: str | None = None,
    ):
        self.app_id = app_id or os.environ.get("GITHUB_APP_ID", "")
        self.private_key = (private_key or os.environ.get("GITHUB_APP_PRIVATE_KEY", "")).replace("\\n", "\n")
        self.installation_id = installation_id or os.environ.get("GITHUB_INSTALLATION_ID", "")
        self._installation_token: str | None = None
        self._token_expires_at: float = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication."""
        if not self.app_id or not self.private_key:
            raise GitHubAuthError(
                "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be set"
            )
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def _get_installation_token(self) -> str:
        """Get or refresh an installation access token."""
        if self._installation_token and time.time() < self._token_expires_at - 60:
            return self._installation_token

        if not self.installation_id:
            raise GitHubAuthError("GITHUB_INSTALLATION_ID must be set")

        client = await self._get_client()
        app_jwt = self._generate_jwt()

        resp = await client.post(
            f"{GITHUB_API}/app/installations/{self.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        self._installation_token = data["token"]
        self._token_expires_at = time.time() + 3500  # ~58 minutes
        return self._installation_token

    async def _headers(self) -> dict[str, str]:
        """Get authenticated headers for API requests."""
        token = await self._get_installation_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ── Check Runs ──────────────────────────────────────────────────────

    async def create_check_run(
        self,
        repo: str,
        sha: str,
        name: str = "AgentCI Eval",
    ) -> str:
        """Create a new check run. Returns the check_run_id."""
        client = await self._get_client()
        headers = await self._headers()

        resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/check-runs",
            headers=headers,
            json={
                "name": name,
                "head_sha": sha,
                "status": "in_progress",
            },
        )
        resp.raise_for_status()
        check_run_id = str(resp.json()["id"])
        logger.info("Created check run %s on %s@%s", check_run_id, repo, sha[:7])
        return check_run_id

    async def update_check_run(
        self,
        repo: str,
        check_run_id: str,
        status: str = "completed",
        conclusion: str | None = None,
        title: str = "",
        summary: str = "",
        text: str = "",
    ) -> None:
        """Update a check run with results."""
        client = await self._get_client()
        headers = await self._headers()

        body: dict[str, Any] = {"status": status}
        if conclusion:
            body["conclusion"] = conclusion
        if title or summary or text:
            body["output"] = {
                "title": title or "AgentCI Results",
                "summary": summary,
                "text": text,
            }

        resp = await client.patch(
            f"{GITHUB_API}/repos/{repo}/check-runs/{check_run_id}",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        logger.info("Updated check run %s → %s/%s", check_run_id, status, conclusion)

    # ── PR Comments ─────────────────────────────────────────────────────

    async def post_pr_comment(self, repo: str, pr_number: int, body: str) -> str:
        """Post a comment on a PR. Returns the comment_id."""
        client = await self._get_client()
        headers = await self._headers()

        resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments",
            headers=headers,
            json={"body": body},
        )
        resp.raise_for_status()
        comment_id = str(resp.json()["id"])
        logger.info("Posted comment %s on %s#%d", comment_id, repo, pr_number)
        return comment_id

    async def find_bot_comment(self, repo: str, pr_number: int) -> str | None:
        """Find an existing AgentCI comment on a PR. Returns comment_id or None."""
        client = await self._get_client()
        headers = await self._headers()

        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments",
            headers=headers,
            params={"per_page": 100},
        )
        resp.raise_for_status()

        for comment in resp.json():
            body = comment.get("body", "")
            if "AgentCI Eval Report" in body or "Powered by AgentCI" in body:
                return str(comment["id"])
        return None

    async def delete_comment(self, repo: str, comment_id: str) -> None:
        """Delete a PR comment."""
        client = await self._get_client()
        headers = await self._headers()

        resp = await client.delete(
            f"{GITHUB_API}/repos/{repo}/issues/comments/{comment_id}",
            headers=headers,
        )
        resp.raise_for_status()
        logger.info("Deleted comment %s on %s", comment_id, repo)

    async def upsert_pr_comment(self, repo: str, pr_number: int, body: str) -> str:
        """Post or update the AgentCI comment on a PR (avoids spam)."""
        existing = await self.find_bot_comment(repo, pr_number)
        if existing:
            await self.delete_comment(repo, existing)
        return await self.post_pr_comment(repo, pr_number, body)

    # ── Commit Status ───────────────────────────────────────────────────

    async def set_commit_status(
        self,
        repo: str,
        sha: str,
        state: str,
        description: str = "",
        context: str = "agentci/eval",
    ) -> None:
        """Set a commit status (pending, success, failure, error)."""
        client = await self._get_client()
        headers = await self._headers()

        resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/statuses/{sha}",
            headers=headers,
            json={
                "state": state,
                "description": description[:140],
                "context": context,
            },
        )
        resp.raise_for_status()
        logger.info("Set status %s on %s@%s", state, repo, sha[:7])
