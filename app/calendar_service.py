from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.models import CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarError(RuntimeError):
    pass


class CalendarService:
    def __init__(self, token_path: Path, calendar_id: str, timezone: str):
        self.token_path, self.calendar_id, self.timezone = token_path, calendar_id, timezone

    def _service(self):
        if not self.token_path.exists():
            raise CalendarError("Google Calendar is not authorized yet. Run the OAuth setup command.")
        try:
            credentials = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.token_path.write_text(credentials.to_json(), encoding="utf-8")
            if not credentials.valid:
                raise CalendarError("Google authorization is invalid or revoked. Run OAuth setup again.")
            return build("calendar", "v3", credentials=credentials, cache_discovery=False)
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError("Could not load Google Calendar authorization.") from exc

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return await asyncio.to_thread(self._list_events, start, end)

    def _list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        try:
            service = self._service()
            items = []
            page_token = None
            while True:
                page = service.events().list(
                    calendarId=self.calendar_id, timeMin=start.astimezone(timezone.utc).isoformat(),
                    timeMax=end.astimezone(timezone.utc).isoformat(), singleEvents=True, orderBy="startTime",
                    pageToken=page_token,
                ).execute()
                items.extend(page.get("items", []))
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
            return [self._convert(item) for item in items if item.get("status") != "cancelled"]
        except HttpError as exc:
            raise CalendarError("Google Calendar is temporarily unavailable.") from exc

    async def create_event(self, action) -> str:
        return await asyncio.to_thread(self._create_event, action)

    def _create_event(self, action) -> str:
        # A stable, Google-valid event ID makes retries after process loss idempotent.
        event_id = hashlib.sha256(action["idempotency_key"].encode()).hexdigest()[:32]
        body = {
            "id": event_id,
            "summary": action["event_title"],
            "start": {"dateTime": action["start_datetime"], "timeZone": action["timezone"]},
            "end": {"dateTime": action["end_datetime"], "timeZone": action["timezone"]},
            "extendedProperties": {"private": {"telecalendar_action_id": action["id"]}},
        }
        if action["location"]:
            body["location"] = action["location"]
        service = self._service()
        try:
            return service.events().insert(calendarId=self.calendar_id, body=body).execute()["id"]
        except HttpError as exc:
            if exc.resp.status == 409:
                # Existing deterministic ID means an earlier retry already succeeded.
                return service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()["id"]
            raise CalendarError("Google Calendar could not create the event. Please try again.") from exc

    def _convert(self, item: dict) -> CalendarEvent:
        tz = ZoneInfo(self.timezone)
        start_data, end_data = item["start"], item["end"]
        if "date" in start_data:
            start_date, end_date = date.fromisoformat(start_data["date"]), date.fromisoformat(end_data["date"])
            start, end, all_day = datetime.combine(start_date, datetime.min.time(), tz), datetime.combine(end_date, datetime.min.time(), tz), True
        else:
            start, end, all_day = datetime.fromisoformat(start_data["dateTime"]), datetime.fromisoformat(end_data["dateTime"]), False
        return CalendarEvent(event_id=item["id"], title=item.get("summary", "(Untitled)"), start=start, end=end,
                             location=item.get("location"), all_day=all_day)
