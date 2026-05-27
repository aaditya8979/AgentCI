"""
Tests for the database pool singleton pattern.

Verifies that:
- get_pool() raises RuntimeError before create_pool() is called
- create_pool() returns a pool and get_pool() returns the same object
- close_pool() then get_pool() raises RuntimeError

Uses sys.modules mocking to avoid requiring asyncpg to be installed.
"""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Mock asyncpg before importing connection module
_mock_asyncpg = MagicMock()
_mock_asyncpg.Pool = MagicMock


@pytest.fixture(autouse=True)
def mock_asyncpg():
    """Mock asyncpg so the connection module can be imported without it installed."""
    with patch.dict(sys.modules, {"asyncpg": _mock_asyncpg}):
        # Force reimport with mock
        if "agentci.db.connection" in sys.modules:
            del sys.modules["agentci.db.connection"]
        if "agentci.db" in sys.modules:
            del sys.modules["agentci.db"]

        from agentci.db import connection
        # Reset pool state
        connection._pool = None
        yield connection
        connection._pool = None

        # Clean up
        if "agentci.db.connection" in sys.modules:
            del sys.modules["agentci.db.connection"]
        if "agentci.db" in sys.modules:
            del sys.modules["agentci.db"]


class TestDatabasePoolSingleton:

    def test_get_pool_before_create_raises(self, mock_asyncpg):
        connection = mock_asyncpg
        with pytest.raises(RuntimeError, match="Database pool not initialised"):
            connection.get_pool()

    @pytest.mark.asyncio
    async def test_create_pool_sets_singleton(self, mock_asyncpg):
        connection = mock_asyncpg
        mock_pool = MagicMock()
        _mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        pool = await connection.create_pool("postgresql://test:test@localhost/test")
        assert pool is mock_pool
        assert connection.get_pool() is mock_pool

    @pytest.mark.asyncio
    async def test_close_pool_then_get_raises(self, mock_asyncpg):
        connection = mock_asyncpg
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        _mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        await connection.create_pool("postgresql://test:test@localhost/test")
        assert connection.get_pool() is mock_pool

        await connection.close_pool()

        with pytest.raises(RuntimeError, match="Database pool not initialised"):
            connection.get_pool()

    @pytest.mark.asyncio
    async def test_create_pool_reuses_existing(self, mock_asyncpg):
        connection = mock_asyncpg
        mock_pool = MagicMock()
        _mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        pool1 = await connection.create_pool("postgresql://test:test@localhost/test")
        pool2 = await connection.create_pool("postgresql://test:test@localhost/test")

        assert pool1 is pool2
        _mock_asyncpg.create_pool.assert_called_once()
