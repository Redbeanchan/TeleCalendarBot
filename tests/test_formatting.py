from datetime import datetime

from app.formatting import compact_event_range, day_heading, event_range, long_date, proposal_date, short_datetime, time_12h


def test_portable_datetime_formats_do_not_use_platform_flags():
    start = datetime(2026, 10, 7, 8, 5)
    end = datetime(2026, 10, 7, 10, 5)

    assert time_12h(start) == "8:05 AM"
    assert short_datetime(start) == "Wed, 7 Oct · 8:05 AM"
    assert long_date(start) == "Wednesday, 7 October 2026"
    assert day_heading(start) == "Wednesday, 7 October"
    assert event_range(start, end) == "8:05 AM – 10:05 AM"
    assert proposal_date(start) == "7 October"
    assert compact_event_range(start, end) == "Wed, 7 Oct · 8:05–10:05 AM"
