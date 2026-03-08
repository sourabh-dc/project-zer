"""
period_calculator.py
--------------------
Pure-function library for generating FinancialPeriod rows from a FinancialCalendar
and FinancialYear.  Supports Gregorian, 4-4-5, 4-5-4, 4-4-4, and custom calendars.

Also provides helpers for resolving the "current period" for a given date.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _weeks_to_months_445(week_index: int, pattern: List[int]) -> int:
    """Return 0-based month index for a given 0-based week index in a retail calendar."""
    week = 0
    for month_idx, weeks in enumerate(pattern):
        for _ in range(weeks):
            if week == week_index:
                return month_idx
            week += 1
    return len(pattern) - 1


def _add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def _period_label(period_type: str, number: int, year_label: str) -> str:
    if period_type == "week":
        return f"W{number:02d}"
    if period_type == "month":
        return f"P{number:02d}"
    if period_type == "quarter":
        return f"Q{number}"
    return f"{year_label}-{period_type[:1].upper()}{number}"


# ---------------------------------------------------------------------------
# Gregorian month split
# ---------------------------------------------------------------------------

def _gregorian_months(start_date: date, end_date: date) -> List[Tuple[date, date, str]]:
    """
    Yield (period_start, period_end, label) for each calendar month between
    start_date and end_date (inclusive).  The first and last months may be partial.
    """
    periods = []
    cursor = start_date
    month_num = 1
    while cursor <= end_date:
        # Find the last day of cursor's month
        if cursor.month == 12:
            next_month_first = date(cursor.year + 1, 1, 1)
        else:
            next_month_first = date(cursor.year, cursor.month + 1, 1)
        month_end = next_month_first - timedelta(days=1)
        period_end = min(month_end, end_date)
        periods.append((cursor, period_end, _period_label("month", month_num, "")))
        month_num += 1
        cursor = next_month_first
        if cursor > end_date:
            break
    return periods


# ---------------------------------------------------------------------------
# Retail calendar generators (4-4-5 / 4-5-4 / 4-4-4)
# ---------------------------------------------------------------------------

def _retail_calendar_periods(
    start_date: date,
    end_date: date,
    pattern: List[int],       # weeks per month, len=12
    period_type: str = "month",
) -> List[Tuple[date, date, str]]:
    """
    Build monthly (or quarterly) periods for a retail week-based calendar.
    `pattern` lists the number of weeks per month (e.g. [4,4,5, 4,4,5, ...]).
    """
    periods = []
    cursor = start_date
    month_num = 1
    for weeks in pattern:
        if cursor > end_date:
            break
        period_end_dt = _add_days(cursor, weeks * 7 - 1)
        period_end = min(period_end_dt, end_date)
        periods.append((cursor, period_end, _period_label(period_type, month_num, "")))
        month_num += 1
        cursor = _add_days(period_end_dt, 1)
    return periods


PATTERNS = {
    "445": [4, 4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5],
    "454": [4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5, 4],
    "444": [4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_periods(
    calendar_type: str,
    start_date: date,
    end_date: date,
    period_type: str = "month",       # month | quarter | week
) -> List[Tuple[date, date, str]]:
    """
    Return a list of (period_start, period_end, label) tuples.

    calendar_type: gregorian | 445 | 454 | 444
    period_type:   month | quarter | week

    For ``custom`` calendars the caller should supply periods manually.
    """
    calendar_type = calendar_type.lower().replace("-", "")

    if calendar_type == "gregorian":
        base = _gregorian_months(start_date, end_date)
    elif calendar_type in PATTERNS:
        base = _retail_calendar_periods(start_date, end_date, PATTERNS[calendar_type])
    else:
        # Unknown: fall back to Gregorian
        base = _gregorian_months(start_date, end_date)

    if period_type == "quarter":
        # Aggregate every 3 months into a quarter
        quarters: List[Tuple[date, date, str]] = []
        for i in range(0, len(base), 3):
            chunk = base[i:i + 3]
            qs = chunk[0][0]
            qe = chunk[-1][1]
            quarters.append((qs, qe, f"Q{i // 3 + 1}"))
        return quarters

    if period_type == "week":
        # Build weekly periods
        weeks = []
        cursor = start_date
        week_num = 1
        while cursor <= end_date:
            week_end = min(_add_days(cursor, 6), end_date)
            weeks.append((cursor, week_end, f"W{week_num:02d}"))
            cursor = _add_days(cursor, 7)
            week_num += 1
        return weeks

    return base  # month


def build_financial_period_rows(
    *,
    tenant_id: uuid.UUID,
    year_id: uuid.UUID,
    calendar_id: uuid.UUID,
    calendar_type: str,
    start_date: date,
    end_date: date,
    period_type: str = "month",
) -> List[dict]:
    """
    Return a list of dicts ready to be passed to ``FinancialPeriod(**row)`` for bulk insert.
    """
    tuples = generate_periods(calendar_type, start_date, end_date, period_type)
    rows = []
    for idx, (ps, pe, label) in enumerate(tuples, start=1):
        rows.append({
            "period_id":     uuid.uuid4(),
            "year_id":       year_id,
            "calendar_id":   calendar_id,
            "tenant_id":     tenant_id,
            "period_number": idx,
            "label":         label,
            "period_type":   period_type,
            "start_date":    ps,
            "end_date":      pe,
        })
    return rows


def get_current_period(db: Session, tenant_id: uuid.UUID, as_of: Optional[date] = None):
    """
    Return the FinancialPeriod that contains ``as_of`` (defaults to today) for
    the tenant's default active calendar.  Returns None if not found.
    """
    from provisioning_service.Models import FinancialPeriod, FinancialYear, FinancialCalendar

    today = as_of or date.today()
    row = (
        db.query(FinancialPeriod)
        .join(FinancialYear, FinancialPeriod.year_id == FinancialYear.year_id)
        .join(FinancialCalendar, FinancialPeriod.calendar_id == FinancialCalendar.calendar_id)
        .filter(
            FinancialCalendar.tenant_id == tenant_id,
            FinancialCalendar.is_active == True,
            FinancialYear.status == "active",
            FinancialPeriod.start_date <= today,
            FinancialPeriod.end_date >= today,
        )
        .order_by(FinancialCalendar.is_default.desc())
        .first()
    )
    return row

