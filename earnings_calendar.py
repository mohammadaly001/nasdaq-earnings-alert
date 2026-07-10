import os
import sys
from datetime import date, timedelta

import requests

from nasdaq100 import NASDAQ100

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
NASDAQ100_SET = set(NASDAQ100)


def get_earnings_calendar(days_ahead: int = 14) -> list:
    if not FINNHUB_API_KEY:
        print("ERROR: FINNHUB_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    future = today + timedelta(days=days_ahead)

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {"from": today.isoformat(), "to": future.isoformat(), "token": FINNHUB_API_KEY}

    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.RequestException as e:
        print(f"ERROR: network request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 401:
        print("ERROR: Finnhub rejected the API key (401). Check FINNHUB_API_KEY.", file=sys.stderr)
        sys.exit(1)
    if response.status_code == 429:
        print("ERROR: Finnhub rate limit hit (429). Try again in a minute.", file=sys.stderr)
        sys.exit(1)
    if response.status_code != 200:
        print(f"ERROR: Finnhub returned HTTP {response.status_code}: {response.text[:300]}", file=sys.stderr)
        sys.exit(1)

    try:
        data = response.json()
    except ValueError:
        print("ERROR: Finnhub response was not valid JSON.", file=sys.stderr)
        sys.exit(1)

    return data.get("earningsCalendar", [])


def check_nasdaq_earnings() -> list:
    earnings = get_earnings_calendar()
    return [item for item in earnings if item.get("symbol") in NASDAQ100_SET]


if __name__ == "__main__":
    companies = check_nasdaq_earnings()
    print("Upcoming NASDAQ Earnings:")

    if not companies:
        print("  (none found in the next 14 days)")

    for company in sorted(companies, key=lambda c: c.get("date", "")):
        print(f"  {company.get('symbol'):<6} {company.get('date')}  {company.get('hour', '')}")
