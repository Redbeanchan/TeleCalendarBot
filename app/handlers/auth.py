from __future__ import annotations

from functools import wraps


def authorized(allowed_user_id: int):
    def decorator(function):
        @wraps(function)
        async def wrapped(update, context):
            user = update.effective_user
            if user is None or user.id != allowed_user_id:
                if update.callback_query:
                    await update.callback_query.answer("This private bot is not available to you.", show_alert=True)
                return None
            database = context.application.bot_data.get("database")
            if database is not None and update.update_id is not None and not database.mark_update(update.update_id):
                return None
            return await function(update, context)
        return wrapped
    return decorator
