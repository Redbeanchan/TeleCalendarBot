from __future__ import annotations

import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.calendar_service import CalendarError

logger = logging.getLogger(__name__)


def callback_handler(allowed_user_id: int):
    from app.handlers.auth import authorized

    @authorized(allowed_user_id)
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()
        try:
            namespace, operation, action_id = query.data.split(":", 2)
        except ValueError:
            await query.edit_message_text("That action is invalid.")
            return
        if namespace != "calendar":
            return
        db = context.application.bot_data["database"]
        if operation == "update":
            action = db.stage_action_for_update(
                action_id, update.effective_user.id, update.effective_chat.id,
                context.application.bot_data["settings"].pending_action_ttl_minutes,
            )
            if action is None:
                await query.edit_message_text("This proposal is no longer pending.")
                return
            await query.edit_message_text("Send the updated details for this event.")
            return
        if operation == "cancel":
            if db.cancel_action(action_id, update.effective_user.id):
                await query.edit_message_text("❌ Calendar event cancelled. Nothing was changed.")
            else:
                await query.edit_message_text("This proposal is no longer pending.")
            return
        if operation != "create":
            return
        action = db.claim_action(action_id, update.effective_user.id)
        if action is None:
            existing = db.get_action(action_id)
            text = "✅ This event was already added." if existing and existing["status"] == "executed" else "This proposal expired or is no longer pending."
            await query.edit_message_text(text)
            return
        try:
            event_id = await context.application.bot_data["calendar"].create_event(action)
            db.complete_action(action_id, event_id)
            start, end = datetime.fromisoformat(action["start_datetime"]), datetime.fromisoformat(action["end_datetime"])
            await query.edit_message_text(f"✅ Added to Google Calendar\n\n{action['event_title']}\n{start.strftime('%a, %#d %b · %#I:%M')}–{end.strftime('%#I:%M %p')}")
        except CalendarError as exc:
            db.release_action(action_id, str(exc))
            await query.edit_message_text(f"{exc}\n\nThe proposal is still pending; try Create again.")
        except Exception:
            db.release_action(action_id, "unexpected error")
            logger.exception("Calendar confirmation failed action=%s", action_id)
            await query.edit_message_text("Calendar creation failed. Nothing was duplicated; please try again.")
    return handle
