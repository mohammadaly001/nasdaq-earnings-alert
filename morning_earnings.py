import os
import sys
from datetime import date
from datetime import timedelta

import requests

from important_stocks import IMPORTANT_STOCKS

IMPORTANT_STOCKS_SET = set(IMPORTANT_STOCKS)

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/earnings"
DAYS_AHEAD = 7


def get_api_key():
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        print("ERROR: missing required environment variable: FINNHUB_API_KEY", file=sys.stderr)
        sys.exit(1)
    return api_key


def format_revenue(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"

    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return "$" + format(value / 1_000_000_000, ".2f") + "B"
    if abs_value >= 1_000_000:
        return "$" + format(value / 1_000_000, ".2f") + "M"
    return "$" + format(value, ",.0f")


def format_eps(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return "$" + format(value, ".2f")


def get_earnings(days_ahead=DAYS_AHEAD):
    api_key = get_api_key()

    today = date.today()
    future = today + timedelta(days=days_ahead)

    params = {
        "from": today.isoformat(),
        "to": future.isoformat(),
        "token": api_key,
    }

    try:
        response = requests.get(FINNHUB_URL, params=params, timeout=10)
    except requests.RequestException as error:
        print("ERROR: network request failed: " + str(error), file=sys.stderr)
        return []

    if response.status_code == 401:
        print("ERROR: Finnhub rejected the API key (401 Unauthorized).", file=sys.stderr)
        return []

    if response.status_code == 429:
        print("ERROR: Finnhub rate limit hit (429). Try again later.", file=sys.stderr)
        return []

    if response.status_code != 200:
        print(
            "ERROR: Finnhub returned HTTP "
            + str(response.status_code)
            + ": "
            + response.text[:300],
            file=sys.stderr,
        )
        return []

    try:
        data = response.json()
    except ValueError:
        print("ERROR: Finnhub response was not valid JSON.", file=sys.stderr)
        return []

    return data.get("earningsCalendar", [])


def days_until(target_date_str):
    try:
        year, month, day = target_date_str.split("-")
        target_date = date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None
    return (target_date - date.today()).days


def filter_important_earnings():
    earnings = get_earnings()

    result = []
    for item in earnings:
        symbol = item.get("symbol")
        if symbol in IMPORTANT_STOCKS_SET:
            result.append(item)

    result.sort(key=lambda item: item.get("date", ""))
    return result


def create_message():
    companies = filter_important_earnings()

    if not companies:
        return "No important NASDAQ earnings found in the next " + str(DAYS_AHEAD) + " days."

    message = "NASDAQ Important Earnings — Next " + str(DAYS_AHEAD) + " Days\n\n"

    for company in companies:
        symbol = company.get("symbol")
        earnings_date = company.get("date", "N/A")
        hour_raw = company.get("hour", "")

        if hour_raw == "bmo":
            hour = "BMO"
        elif hour_raw == "amc":
            hour = "AMC"
        else:
            hour = "N/A"

        days_left = days_until(earnings_date)
        days_left_text = str(days_left) if days_left is not None else "N/A"

        revenue = format_revenue(company.get("revenueEstimate"))
        eps = format_eps(company.get("epsEstimate"))

        message += symbol + "\n\n"
        message += "Date: " + earnings_date + "\n"
        message += "Days Left: " + days_left_text + "\n"
        message += "Time: " + hour + "\n\n"
        message += "Revenue Estimate: " + revenue + "\n"
        message += "EPS Estimate: " + eps + "\n\n"
        message += "----------------\n\n"

    return message.strip()


if __name__ == "__main__":
    print(create_message())
