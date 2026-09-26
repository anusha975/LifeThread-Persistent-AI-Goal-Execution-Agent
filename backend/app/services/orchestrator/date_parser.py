import re
from datetime import UTC, datetime, timedelta


class DateParser:
    """Natural-language date parser resolving relative and colloquial date expressions into UTC datetimes."""

    WEEKDAYS = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }

    MONTHS = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    @classmethod
    def parse_deadline(cls, text: str, base_time: datetime | None = None) -> datetime | None:
        """Parse text into a timezone-aware UTC datetime set to end of standard business hours (18:00 UTC)."""
        now = base_time or datetime.now(UTC)
        raw = text.strip().lower()

        # Clean common filler words
        raw = re.sub(r"^(?:by|to|on|until|at|for|the)\s+", "", raw).strip()

        # 1. "tomorrow"
        if "tomorrow" in raw:
            target = now + timedelta(days=1)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

        # 2. "day after tomorrow"
        if "day after tomorrow" in raw:
            target = now + timedelta(days=2)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

        # 3. "in X days" / "X days"
        in_days_match = re.search(r"\b(?:in\s+)?(\d+)\s+days?\b", raw)
        if in_days_match:
            days = int(in_days_match.group(1))
            target = now + timedelta(days=days)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

        # 4. "in X weeks" / "next week"
        if "next week" in raw:
            target = now + timedelta(days=7)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

        in_weeks_match = re.search(r"\b(?:in\s+)?(\d+)\s+weeks?\b", raw)
        if in_weeks_match:
            weeks = int(in_weeks_match.group(1))
            target = now + timedelta(days=weeks * 7)
            return target.replace(hour=18, minute=0, second=0, microsecond=0)

        # 5. Weekdays (e.g. "friday", "this friday", "next friday", "next monday")
        for day_name, day_idx in cls.WEEKDAYS.items():
            if re.search(rf"\b(?:this\s+|next\s+)?{day_name}\b", raw):
                current_day_idx = now.weekday()
                days_ahead = (day_idx - current_day_idx) % 7
                if days_ahead == 0:
                    # If today is Friday and user says "Friday", schedule for next Friday (7 days)
                    days_ahead = 7
                if "next " in raw and days_ahead < 7:
                    days_ahead += 7
                target = now + timedelta(days=days_ahead)
                return target.replace(hour=18, minute=0, second=0, microsecond=0)

        # 6. Specific month + day (e.g. "oct 15", "october 15th", "nov 3")
        for month_name, month_num in cls.MONTHS.items():
            match = re.search(rf"\b{month_name}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", raw)
            if match:
                day_num = int(match.group(1))
                year = now.year
                try:
                    candidate = datetime(year, month_num, day_num, 18, 0, 0, tzinfo=UTC)
                    if candidate < now:
                        candidate = datetime(year + 1, month_num, day_num, 18, 0, 0, tzinfo=UTC)
                    return candidate
                except ValueError:
                    return None

        # 7. ISO format YYYY-MM-DD
        iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
        if iso_match:
            try:
                y = int(iso_match.group(1))
                m = int(iso_match.group(2))
                d = int(iso_match.group(3))
                return datetime(y, m, d, 18, 0, 0, tzinfo=UTC)
            except ValueError:
                return None

        return None
