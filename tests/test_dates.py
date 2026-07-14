"""Milestone 3: extended TW date synonyms and expressions."""

from datetime import datetime, timedelta, timezone

import pytest

from taskpeasant._dates import parse_date, resolve_date, resolve_date_dt


def now():
    return datetime.now(timezone.utc)


def test_legacy_aliases_still_work():
    assert resolve_date("today") == now().strftime("%Y-%m-%d")
    assert resolve_date("tomorrow") == \
        (now() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert resolve_date("+3d") == \
        (now() + timedelta(days=3)).strftime("%Y-%m-%d")
    assert resolve_date("someday").startswith(str(now().year + 9))


def test_negative_offsets():
    assert resolve_date("-2d") == (now() - timedelta(days=2)).strftime("%Y-%m-%d")
    assert resolve_date("-1w") == (now() - timedelta(weeks=1)).strftime("%Y-%m-%d")


def test_unit_words():
    assert resolve_date("+2wks") == \
        (now() + timedelta(weeks=2)).strftime("%Y-%m-%d")
    assert resolve_date("+10days") == \
        (now() + timedelta(days=10)).strftime("%Y-%m-%d")


def test_hour_and_minute_offsets_carry_time():
    r = resolve_date("+3h")
    assert "T" in r and r.endswith("Z")
    r = resolve_date("+90min")
    assert "T" in r


def test_compound_alias_offset():
    eom = resolve_date_dt("eom")
    assert resolve_date_dt("eom-2d") == eom - timedelta(days=2)
    monday = resolve_date_dt("monday")
    assert resolve_date_dt("monday+1w") == monday + timedelta(weeks=1)


def test_eod_sod():
    sod = resolve_date_dt("sod")
    eod = resolve_date_dt("eod")
    assert sod.hour == 0 and sod.minute == 0
    assert eod.hour == 23 and eod.minute == 59
    assert eod - sod == timedelta(days=1) - timedelta(seconds=1)


def test_quarters():
    soq = resolve_date_dt("soq")
    eoq = resolve_date_dt("eoq")
    assert soq.day == 1 and soq.month in (1, 4, 7, 10)
    assert eoq.month in (3, 6, 9, 12)
    assert soq <= now() <= eoq + timedelta(days=1)


def test_ordinal_next_occurrence():
    dt = resolve_date_dt("23rd")
    assert dt.day == 23
    assert dt > now() - timedelta(days=1)
    # An ordinal earlier than today rolls to next month
    yesterday_ord = (now() - timedelta(days=1)).day
    if yesterday_ord != now().day:   # skip on month boundary edge
        rolled = resolve_date_dt(f"{yesterday_ord}th")
        assert rolled.month != now().month or rolled.year != now().year


def test_epoch():
    dt = resolve_date_dt("1767225600")
    assert dt == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_garbage_unchanged():
    assert resolve_date("garbage") == "garbage"
    assert parse_date("garbage") is None


def test_literal_dates_pass_through():
    assert resolve_date("2026-07-01") == "2026-07-01"
    assert resolve_date("2026-07-01T10:00:00Z") == "2026-07-01T10:00:00Z"
    assert resolve_date("20260701T100000Z") == "20260701T100000Z"


def test_parse_date_resolves_synonyms():
    assert parse_date("today") is not None
    assert parse_date("eoq") is not None
    assert parse_date("now+1h") is not None
