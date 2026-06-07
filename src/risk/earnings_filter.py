import logging
from datetime import date
from pathlib import Path

import yaml

logger = logging.getLogger("risk.earnings_filter")


class EarningsCalendarFilter:
    def __init__(self, yaml_path: str = "config/earnings_calendar.yaml"):
        self.yaml_path = Path(yaml_path)
        self._calendar: dict[str, list[str]] = {}
        self.load_calendar()

    def load_calendar(self) -> None:
        try:
            if self.yaml_path.exists():
                with self.yaml_path.open("r") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        self._calendar = data
                logger.info(
                    "Loaded earnings calendar from %s with %d symbols",
                    self.yaml_path,
                    len(self._calendar),
                )
            else:
                logger.warning(
                    "Earnings calendar file %s not found. Using empty calendar.", self.yaml_path
                )
                self._calendar = {}
        except Exception as e:
            logger.error("Error loading earnings calendar: %s", e)
            self._calendar = {}

    def is_near_earnings(self, symbol: str, check_date: date) -> bool:
        """Check if check_date is near (±1 day) any earnings date for symbol."""
        dates_str = self._calendar.get(symbol)
        if not dates_str:
            return False

        for date_str in dates_str:
            try:
                # Support YYYY-MM-DD format
                earnings_date = date.fromisoformat(date_str)
                # Check if check_date falls within [earnings_date - 1 day, earnings_date + 1 day]
                if abs((check_date - earnings_date).days) <= 1:
                    return True
            except ValueError as e:
                logger.warning(
                    "Invalid date format in earnings calendar for %s: %s (%s)", symbol, date_str, e
                )
        return False
