"""
taskpeasant/_calendar_grid.py
Shared month-grid math for `reports.py::cmd_calendar` (plain text) and
`_rich.py::render_calendar` (colored) — kept in one place so weekstart /
week-number handling exists exactly once.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import List, Tuple


def month_weeks(year: int, month: int,
                monday_first: bool) -> List[Tuple[int, List[date]]]:
    """One (iso_week_number, [7 dates]) pair per grid row.

    Padding dates from the adjacent month are included as real `date`
    objects (for correct weekday alignment) — callers blank the cell
    where `d.month != month`.
    """
    cal = calendar.Calendar(firstweekday=0 if monday_first else 6)
    rows = []
    for week in cal.monthdatescalendar(year, month):
        monday = week[0] if monday_first else week[1]
        rows.append((monday.isocalendar()[1], week))
    return rows
