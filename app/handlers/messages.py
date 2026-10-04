from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.calendar_service import CalendarError
from app.calendar_conversation import calendar_followup
from app.date_resolver import DateResolutionError, default_duration
from app.intent_parser import IntentParseError
from app.models import IntentType, ParsedIntent
from app.schedule_summary import summary_range, send_summary
from app.scheduling import format_title, recurring_intent, recurrence_description

logger = logging.getLogger(__name__)


def message_handler(allowed_user_id: int, command_text=None):
    from app.handlers.auth import authorized

    @authorized(allowed_user_id)
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message or not message.text:
            return
        services = context.application.bot_data
        text = command_text(context) if command_text else message.text
        try:
            now = datetime.now(ZoneInfo(services["settings"].timezone))
            interval = summary_range(text, now)
            if interval:
                logger.info("Schedule summary requested start=%s end=%s", *interval)
                await send_summary(message, services, update.effective_user.id, update.effective_chat.id, *interval)
                return
            draft = services["database"].get_calendar_draft(update.effective_user.id, update.effective_chat.id)
            intent = recurring_intent(text, now) or calendar_followup(text, draft)
            source = "direct parsing"
            if intent is None:
                source = "Ollama"
                intent = await services["intent_parser"].parse(text)
            logger.info("Intent classified type=%s confidence=%.2f", intent.intent, intent.confidence)
            if draft and intent.intent in {IntentType.PROPOSE_CALENDAR_EVENT, IntentType.UNKNOWN}:
                intent = _merge_calendar_draft(intent, draft, text)
            if intent.title:
                intent.title = format_title(intent.title)
            if services.get("debug_enabled"):
                logger.info("TRACE source=%s draft=%s extracted=%s", source, dict(draft) if draft else None, intent.model_dump())
            if intent.intent == IntentType.PROPOSE_CALENDAR_EVENT and intent.date_expression:
                # Freeze relative dates when received, even if the title arrives on another day.
                intent.date_expression = services["date_resolver"].resolve_date(intent.date_expression).isoformat()
            if intent.intent == IntentType.PROPOSE_CALENDAR_EVENT and _is_incomplete_calendar_intent(intent):
                services["database"].upsert_calendar_draft(
                    update.effective_user.id, update.effective_chat.id, intent.title, intent.date_expression, intent.time,
                    intent.end_time, intent.location, services["settings"].timezone, services["settings"].pending_action_ttl_minutes,
                )
                if services.get("debug_enabled"):
                    logger.info("TRACE saved draft=%s", intent.model_dump())
                await message.reply_text(_calendar_draft_prompt(intent))
                return
            if intent.needs_clarification or intent.confidence < 0.55:
                await message.reply_text(_clarification(intent))
                return
            resolved = services["date_resolver"].resolve(intent)
            if intent.intent == IntentType.CREATE_REMINDER:
                if not intent.title:
                    await message.reply_text("What should I remind you about?")
                    return
                reminder_id = services["database"].create_reminder(update.effective_user.id, update.effective_chat.id, intent.title, resolved.start, services["settings"].timezone, intent.recurrence_rule)
                repeat = "\nRepeats: " + recurrence_description(intent.recurrence_rule) if intent.recurrence_rule else ""
                await message.reply_text(f"🔔 Reminder set\n\n{intent.title}\n{resolved.start.strftime('%a, %d %b · %I:%M %p')}{repeat}\nID: {reminder_id}")
            elif intent.intent == IntentType.PROPOSE_CALENDAR_EVENT:
                if not intent.title:
                    await message.reply_text("What should I call this event?")
                    return
                end = resolved.end or resolved.start + default_duration(intent.title)
                action_id = services["database"].create_pending_action(
                    update.effective_user.id, intent.title, resolved.start, end, services["settings"].timezone,
                    intent.location, services["settings"].pending_action_ttl_minutes,
                )
                services["database"].clear_calendar_draft(update.effective_user.id, update.effective_chat.id)
                if services.get("debug_enabled"):
                    logger.info("TRACE proposal id=%s title=%s start=%s end=%s; waiting for Yes", action_id, intent.title, resolved.start, end)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Yes", callback_data=f"calendar:create:{action_id}"),
                    InlineKeyboardButton("No", callback_data=f"calendar:cancel:{action_id}"),
                    InlineKeyboardButton("Edit details", callback_data=f"calendar:update:{action_id}"),
                ]])
                await message.reply_text(_proposal(intent.title, resolved.start, end, intent.location), reply_markup=keyboard)
            elif intent.intent == IntentType.QUERY_CALENDAR:
                await send_summary(message, services, update.effective_user.id, update.effective_chat.id,
                                   resolved.start, resolved.end or resolved.start + timedelta(days=1))
            else:
                await message.reply_text("I can set reminders, propose calendar events, or check your schedule. What would you like?")
        except (IntentParseError, DateResolutionError, CalendarError) as exc:
            logger.info("Request could not be completed: %s", exc)
            await message.reply_text(str(exc))
        except Exception:
            logger.exception("Unexpected message handling failure")
            await message.reply_text("Something went wrong. Nothing was changed; please try again.")
    return handle


def _has_calendar_details(intent: ParsedIntent) -> bool:
    return any([intent.title, intent.date_expression, intent.time, intent.end_time, intent.location])


def _is_incomplete_calendar_intent(intent: ParsedIntent) -> bool:
    return not (intent.title and intent.date_expression and intent.time)


def _merge_calendar_draft(intent: ParsedIntent, draft, message_text: str) -> ParsedIntent:
    data = {
        "intent": IntentType.PROPOSE_CALENDAR_EVENT,
        "title": intent.title or draft["title"],
        "date_expression": intent.date_expression or draft["date_expression"],
        "time": intent.time or draft["event_time"],
        "end_time": intent.end_time or draft["end_time"],
        "location": intent.location if intent.location is not None else draft["location"],
        "confidence": max(intent.confidence, 0.9),
        "missing_fields": [],
        "needs_clarification": False,
    }
    if not data["title"] and not any([intent.date_expression, intent.time, intent.end_time, intent.location]):
        data["title"] = message_text.strip()[:500] or None
    missing = []
    if not data["title"]:
        missing.append("title")
    if not data["date_expression"]:
        missing.append("day")
    if not data["time"]:
        missing.append("time")
    data["missing_fields"] = missing
    data["needs_clarification"] = bool(missing)
    return ParsedIntent(**data)


def _clarification(intent) -> str:
    subject = intent.title or "that"
    return f"🗓️ {subject} needs more detail.\n\nWhat day and time should I use?"


def _calendar_draft_prompt(intent: ParsedIntent) -> str:
    if not intent.title:
        return "What should I name this event?"
    if not intent.date_expression:
        return f"When should I schedule {intent.title}?"
    if not intent.time:
        return f"What time should I schedule {intent.title}?"
    return f"What else should I update for {intent.title}?"


def _proposal(title, start, end, location) -> str:
    where = f"\n📍 {location}" if location else ""
    day = f"{start.day} {start.strftime('%B %Y')}"
    event_time = f"{start.hour % 12 or 12}:{start.minute:02d} {start.strftime('%p')}"
    return f'Shall I create an event for {day} called "{title}", at {event_time}?{where}'


def _event_list(day, events, timezone) -> str:
    heading = day.astimezone(timezone).strftime("%A, %#d %B")
    if not events:
        return f"📅 {heading}\n\nNothing scheduled."
    lines = []
    for event in events:
        when = "All day" if event.all_day else event.start.astimezone(timezone).strftime("%#I:%M %p")
        lines.append(f"• {when} — {event.title}")
    return f"📅 {heading}\n\n" + "\n".join(lines)
