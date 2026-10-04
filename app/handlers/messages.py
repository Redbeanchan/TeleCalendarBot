from __future__ import annotations

import logging
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.calendar_service import CalendarError
from app.date_resolver import DateResolutionError, default_duration
from app.formatting import day_heading, event_range, proposal_date, short_datetime, time_12h
from app.intent_parser import IntentParseError
from app.models import IntentType, ParsedIntent

logger = logging.getLogger(__name__)


def message_handler(allowed_user_id: int):
    from app.handlers.auth import authorized

    @authorized(allowed_user_id)
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message or not message.text:
            return
        services = context.application.bot_data
        try:
            draft_data = context.user_data.get("calendar_draft")
            if draft_data:
                draft = ParsedIntent.model_validate(draft_data)
                if _required_missing(draft) == ["title"]:
                    intent = ParsedIntent.model_validate({
                        **draft.model_dump(),
                        "title": message.text.strip()[:500],
                        "confidence": 1.0,
                    })
                else:
                    intent = await services["intent_parser"].update(draft, message.text)
            else:
                intent = await services["intent_parser"].parse(message.text)
            logger.info("Intent classified type=%s confidence=%.2f", intent.intent, intent.confidence)
            missing = _required_missing(intent)
            if missing:
                if intent.intent == IntentType.PROPOSE_CALENDAR_EVENT:
                    context.user_data["calendar_draft"] = intent.model_dump(mode="json")
                await message.reply_text(_clarification(intent, missing))
                return
            context.user_data.pop("calendar_draft", None)
            if intent.confidence < 0.55:
                await message.reply_text("I’m not certain I understood. Could you rephrase the plan with a day and time?")
                return
            resolved = services["date_resolver"].resolve(intent)
            if intent.intent == IntentType.CREATE_REMINDER:
                if not intent.title:
                    await message.reply_text("What should I remind you about?")
                    return
                services["database"].create_reminder(update.effective_user.id, update.effective_chat.id, intent.title, resolved.start, services["settings"].timezone)
                await message.reply_text(f"🔔 Reminder set\n\n{intent.title}\n{short_datetime(resolved.start)}")
            elif intent.intent == IntentType.PROPOSE_CALENDAR_EVENT:
                if not intent.title:
                    await message.reply_text("What should I call this event?")
                    return
                end = resolved.end or resolved.start + default_duration(intent.title)
                action_id = services["database"].create_pending_action(
                    update.effective_user.id, intent.title, resolved.start, end, services["settings"].timezone,
                    intent.location, services["settings"].pending_action_ttl_minutes,
                )
                old_action_id = context.user_data.pop("editing_action_id", None)
                if old_action_id:
                    services["database"].cancel_action(old_action_id, update.effective_user.id)
                keyboard = _proposal_keyboard(action_id)
                await message.reply_text(_proposal(intent.title, resolved.start, end, intent.location), reply_markup=keyboard)
            elif intent.intent == IntentType.QUERY_CALENDAR:
                events = await services["calendar"].list_events(resolved.start, resolved.end or resolved.start + timedelta(days=1))
                await message.reply_text(_event_list(resolved.start, events, ZoneInfo(services["settings"].timezone)))
            else:
                await message.reply_text("I can set reminders, propose calendar events, or check your schedule. What would you like?")
        except (IntentParseError, DateResolutionError, CalendarError) as exc:
            logger.info("Request could not be completed: %s", exc)
            await message.reply_text(str(exc))
        except Exception:
            logger.exception("Unexpected message handling failure")
            await message.reply_text("Something went wrong. Nothing was changed; please try again.")
    return handle


def _required_missing(intent: ParsedIntent) -> list[str]:
    if intent.intent not in {IntentType.CREATE_REMINDER, IntentType.PROPOSE_CALENDAR_EVENT}:
        return []
    missing = []
    if not intent.title:
        missing.append("title")
    if not intent.date_expression:
        missing.append("date")
    relative_duration = bool(re.fullmatch(r"in\s+\d+\s+(minute|hour)s?", (intent.date_expression or "").lower()))
    implied_time = (intent.date_expression or "").lower() in {"tonight", "this evening"}
    if not intent.time and not relative_duration and not implied_time:
        missing.append("time")
    return missing


def _clarification(intent: ParsedIntent, missing: list[str]) -> str:
    if missing == ["title"]:
        return "What should I call this event?"
    questions = {"title": "what to call it", "date": "which day", "time": "what time"}
    details = ", ".join(questions[item] for item in missing[:-1])
    if len(missing) > 1:
        details += f" and {questions[missing[-1]]}"
    else:
        details = questions[missing[0]]
    subject = intent.title or "this plan"
    return f"I can add “{subject}”. Just tell me {details}."


def _proposal_keyboard(action_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"calendar:create:{action_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"calendar:cancel:{action_id}"),
        ],
        [InlineKeyboardButton("✏️ Update details", callback_data=f"calendar:update:{action_id}")],
    ])


def _proposal(title, start, end, location) -> str:
    where = f"\n📍 {location}" if location else ""
    return f"📅 Should I update your calendar?\n\n{proposal_date(start)} · {event_range(start, end)}\n{title}{where}"


def _event_list(day, events, timezone) -> str:
    heading = day_heading(day.astimezone(timezone))
    if not events:
        return f"📅 {heading}\n\nNothing scheduled."
    lines = []
    for event in events:
        when = "All day" if event.all_day else time_12h(event.start.astimezone(timezone))
        lines.append(f"• {when} — {event.title}")
    return f"📅 {heading}\n\n" + "\n".join(lines)
