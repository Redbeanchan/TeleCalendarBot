import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.handlers.auth import authorized


class DB:
    def mark_update(self, update_id):
        return True


def test_authorized_user_runs_handler():
    called = False

    @authorized(42)
    async def handler(update, context):
        nonlocal called
        called = True

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), callback_query=None, update_id=1)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": DB()}))
    asyncio.run(handler(update, context))
    assert called


def test_unauthorized_user_is_rejected():
    called = False

    @authorized(42)
    async def handler(update, context):
        nonlocal called
        called = True

    query = SimpleNamespace(answer=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=99), callback_query=query, update_id=1)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": DB()}))
    asyncio.run(handler(update, context))
    assert not called
    query.answer.assert_awaited_once()
