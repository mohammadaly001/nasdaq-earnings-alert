import os
import sys
from datetime import date, timedelta

import requests

from important_stocks import IMPORTANT_STOCKS

IMPORTANT_STOCKS_SET = set(IMPORTANT_STOCKS)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


FINNHUB_API_KEY = _require_env("FINNHUB_API_KEY")


def _fmt_money(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"${value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"${value / 1e6:.2f}M"
    return f"${value:,.0f}"


def _fmt_eps(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def get_earnings(days_ahead: int = 30) -> list:
    today = date.today()
    future = today + timedelta(days=days_ahead)

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": today.isoformat(),
        "to": future.isoformat(),
        "token": FINNHUB_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.RequestException as e:
        print(f"ERROR: network request failed: {e}", file=sys.stderr)
        return []

    if response.status_code == 401:
        print("ERROR: Finnhub rejected the API key (401 Unauthorized).", file=sys.stderr)
        return []
    if response.status_code == 429:
        print("ERROR: Finnhub rate limit hit (429). Try again in a minute.", file=sys.stderr)
        return []
    if response.status_code != 200:
        print(f"ERROR: Finnhub returned HTTP {response.status_code}: {response.text[:300]}", file=sys.stderr)
        return []

    try:
        data = response.json()
    except ValueError:
        print("ERROR: Finnhub response was not valid JSON.", file=sys.stderr)
        return []

    return data.get("earningsCalendar", [])


def filter_important_earnings() -> list:
    earnings = get_earnings()
    result = [item for item in earnings if item.get("symbol") in IMPORTANT_STOCKS_SET]
    result.sort(key=lambda item: item.get("date", ""))
    return result


def create_message() -> str:
    companies = filter_important_earnings()

    if not companies:
        return "No important NASDAQ earnings found in the next 30 days."

    message = "NASDAQ Earnings — Next 30 Days\n\n"

    for company in companies:
        symbol = company.get("symbol")
        earnings_date = company.get("date")
        hour = company.get("hour", "") or "N/A"

        revenue = _fmt_money(company.get("revenueEstimate"))
        eps = _fmt_eps(company.get("epsEstimate"))

        message += (
            f"{symbol}\n\n"
            f"Date: {earnings_date}\n"
            f"Time: {hour}\n\n"
            f"Revenue Estimate: {revenue}\n"
            f"EPS Estimate: {eps}\n\n"
            f"----------------\n\n"
        )

    return message.strip()


if __name__ == "__main__":
    print(create_message())
