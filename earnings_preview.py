import os
import sys
from datetime import date
from datetime import timedelta

import requests

from important_stocks import IMPORTANT_STOCKS

IMPORTANT_STOCKS_SET = set(IMPORTANT_STOCKS)

FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings"

# FMP's legacy /api/v3/ endpoints are being phased out in favor of the
# unified /stable/ endpoints (confirmed against FMP's current documentation
# at site.financialmodelingprep.com/developer/docs/stable). All FMP calls
# in this file use /stable/.
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

REQUEST_TIMEOUT = 10

# NOTE: FMP's stable docs describe the field content of each endpoint but
# do not publish an exact JSON schema in the page text. The field names
# below (revenue/eps on income-statement, epsActual/epsEstimated etc. on
# the earnings endpoint) are FMP's documented/conventional names as of
# this writing. _first_present() below tries several plausible name
# variants for the actual-vs-estimate fields specifically, so a naming
# difference degrades to "N/A" instead of crashing. If you see unexpected
# N/A values in the Beat/Miss section, run once locally, print the raw
# FMP response, and adjust the candidate key lists near the top of
# build_quarterly_section().


# ---------------------------------------------------------------------------
# Environment / API keys
# ---------------------------------------------------------------------------

def get_finnhub_key():
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        print("ERROR: missing required environment variable: FINNHUB_API_KEY", file=sys.stderr)
        sys.exit(1)
    return api_key


def get_fmp_key():
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("ERROR: missing required environment variable: FMP_API_KEY", file=sys.stderr)
        sys.exit(1)
    return api_key


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

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


def format_hour(hour_raw):
    if hour_raw == "bmo":
        return "BMO"
    if hour_raw == "amc":
        return "AMC"
    return "N/A"


def quarter_label(target_quarter, offset):
    """
    Returns the fiscal quarter number that is `offset` quarters before
    target_quarter, wrapping around the 1-4 boundary
    (e.g. target=1, offset=1 -> 4, the prior fiscal year's Q4).
    """
    q = target_quarter - offset
    while q < 1:
        q += 4
    return q


def _first_present(row, keys):
    """Returns the first non-None value found under any of `keys`."""
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


# ---------------------------------------------------------------------------
# Trading-day-aware "tomorrow"
# ---------------------------------------------------------------------------

def next_trading_day(base_date):
    """
    Returns the next US market trading day after base_date, skipping
    Saturday and Sunday. Does NOT account for market holidays (e.g. July
    4th, Thanksgiving) since Finnhub's calendar simply won't have an
    entry on those dates anyway - a holiday just means an empty result,
    which is handled gracefully like any other day with no earnings.
    """
    next_day = base_date + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        next_day += timedelta(days=1)
    return next_day


# ---------------------------------------------------------------------------
# Generic HTTP helper - shared error handling for both APIs
# ---------------------------------------------------------------------------

def safe_get_json(url, params, source_name):
    """
    Returns the parsed JSON body, or None if anything goes wrong. Never
    raises - callers treat None as "no data available" and fall back to
    N/A rather than crashing.
    """
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        print("ERROR: " + source_name + " network request failed: " + str(error), file=sys.stderr)
        return None

    if response.status_code == 401:
        print("ERROR: " + source_name + " rejected the API key (401 Unauthorized).", file=sys.stderr)
        return None

    if response.status_code == 429:
        print("ERROR: " + source_name + " rate limit hit (429).", file=sys.stderr)
        return None

    if response.status_code != 200:
        print(
            "ERROR: " + source_name + " returned HTTP "
            + str(response.status_code) + ": " + response.text[:300],
            file=sys.stderr,
        )
        return None

    try:
        return response.json()
    except ValueError:
        print("ERROR: " + source_name + " response was not valid JSON.", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Finnhub: next trading day's earnings calendar
# ---------------------------------------------------------------------------

def get_next_trading_day_earnings():
    """
    Returns Finnhub calendar entries for the next US trading day
    (tomorrow, or the following Monday if tomorrow falls on a weekend),
    filtered to IMPORTANT_STOCKS.
    """
    api_key = get_finnhub_key()
    target_date = next_trading_day(date.today())

    params = {
        "from": target_date.isoformat(),
        "to": target_date.isoformat(),
        "token": api_key,
    }

    data = safe_get_json(FINNHUB_CALENDAR_URL, params, "Finnhub")
    if not data:
        return []

    entries = data.get("earningsCalendar", [])
    return [entry for entry in entries if entry.get("symbol") in IMPORTANT_STOCKS_SET]


# ---------------------------------------------------------------------------
# FMP: historical quarterly and annual financials, with per-symbol caching
# ---------------------------------------------------------------------------

# Module-level cache: symbol -> {"quarterly": [...], "earnings": [...], "annual": [...]}
# Populated once per symbol per run via get_company_financials(), so a
# symbol's data is never fetched from FMP more than once even if multiple
# parts of the message-building code need it.
_fmp_cache = {}


def _fmp_get_list(path, symbol, extra_params=None):
    api_key = get_fmp_key()
    params = {"symbol": symbol, "apikey": api_key}
    if extra_params:
        params.update(extra_params)

    data = safe_get_json(FMP_BASE_URL + path, params, "FMP")
    if not isinstance(data, list):
        return []
    return data


def get_company_financials(symbol):
    """
    Fetches (and caches) everything needed from FMP for one symbol in a
    single grouped call site: quarterly income statement, the earnings
    report history (for Beat/Miss), and annual income statement. Repeat
    calls for the same symbol within one run return the cached result
    instead of hitting the API again.
    """
    if symbol in _fmp_cache:
        return _fmp_cache[symbol]

    quarterly = _fmp_get_list("/income-statement", symbol, {"period": "quarter", "limit": 4})
    earnings_history = _fmp_get_list("/earnings", symbol, {"limit": 8})
    annual = _fmp_get_list("/income-statement", symbol, {"period": "annual", "limit": 2})

    result = {
        "quarterly": quarterly,
        "earnings": earnings_history,
        "annual": annual,
    }
    _fmp_cache[symbol] = result
    return result


def beat_miss_label(actual, estimate):
    if actual is None or estimate is None:
        return ""
    try:
        actual = float(actual)
        estimate = float(estimate)
    except (TypeError, ValueError):
        return ""
    if actual > estimate:
        return " (Beat)"
    if actual < estimate:
        return " (Miss)"
    return " (In-line)"


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------

def build_quarterly_section(symbol, target_quarter, financials):
    """
    Builds the "Q1: $X | EPS $Y (Beat)" lines for the three fiscal
    quarters immediately before the upcoming one. Returns a list of
    strings, oldest quarter first. Returns [] if FMP has no data.
    """
    quarterly = financials["quarterly"]
    if not quarterly:
        return []

    earnings_history = financials["earnings"]
    surprise_by_date = {}
    for row in earnings_history:
        row_date = row.get("date")
        if not row_date:
            continue
        actual = _first_present(row, ["epsActual", "actualEarningResult", "eps"])
        estimate = _first_present(row, ["epsEstimated", "estimatedEarning", "epsEstimate"])
        surprise_by_date[row_date] = {"actual": actual, "estimate": estimate}

    # FMP returns newest first; the three rows right after the current
    # (unreported) quarter are the three most recent reported quarters.
    recent_three = quarterly[:3]
    recent_three = list(reversed(recent_three))  # oldest first, matches example order

    lines = []
    for offset, row in zip(range(len(recent_three), 0, -1), recent_three):
        label_q = quarter_label(target_quarter, offset)
        revenue = format_revenue(row.get("revenue"))
        eps = format_eps(row.get("eps"))

        row_date = row.get("date")
        surprise = surprise_by_date.get(row_date, {})
        beat_miss = beat_miss_label(surprise.get("actual"), surprise.get("estimate"))

        lines.append("Q" + str(label_q) + ": " + revenue + " | EPS " + eps + beat_miss)

    return lines


def build_annual_section(financials):
    """
    Builds the "FY25 EPS: $X vs $Y in FY24" line. Returns "" if FMP has
    no annual data.
    """
    annual = financials["annual"]
    if len(annual) < 2:
        return ""

    recent_year = annual[0]
    prior_year = annual[1]

    recent_label = str(recent_year.get("calendarYear", "N/A"))[-2:]
    prior_label = str(prior_year.get("calendarYear", "N/A"))[-2:]

    recent_eps = format_eps(recent_year.get("eps"))
    prior_eps = format_eps(prior_year.get("eps"))

    return "FY" + recent_label + " EPS: " + recent_eps + " vs " + prior_eps + " in FY" + prior_label


def build_company_block(entry):
    symbol = entry.get("symbol", "N/A")
    quarter = entry.get("quarter")
    year = entry.get("year")

    if quarter is None or year is None:
        quarter_year_label = "Q? FY??"
    else:
        quarter_year_label = "Q" + str(quarter) + " FY" + str(year)[-2:]

    lines = ["$" + symbol + " " + quarter_year_label + " Earnings Tomorrow", ""]

    financials = get_company_financials(symbol)

    if quarter is not None:
        quarterly_lines = build_quarterly_section(symbol, quarter, financials)
        if quarterly_lines:
            lines.extend(quarterly_lines)
            lines.append("")

    estimate_quarter_label = "Q" + str(quarter) if quarter is not None else "Q?"
    lines.append(estimate_quarter_label + " Estimate:")
    lines.append("Revenue: " + format_revenue(entry.get("revenueEstimate")))
    lines.append("EPS: " + format_eps(entry.get("epsEstimate")))

    annual_line = build_annual_section(financials)
    if annual_line:
        lines.append("")
        lines.append(annual_line)

    return "\n".join(lines)


def create_preview_message():
    """
    Builds the full preview text for every important company reporting
    on the next US trading day. Returns a plain string only - this
    function does NOT send anything to Telegram. Wire it up separately,
    e.g.:

        from earnings_preview import create_preview_message
        from send_telegram import send_telegram
        send_telegram(create_preview_message())
    """
    _fmp_cache.clear()  # fresh cache each call, in case this is imported and reused

    entries = get_next_trading_day_earnings()

    if not entries:
        return "No important NASDAQ earnings tomorrow."

    entries.sort(key=lambda entry: entry.get("symbol", ""))

    blocks = [build_company_block(entry) for entry in entries]
    return ("\n\n----------------\n\n").join(blocks)


if __name__ == "__main__":
    print(create_preview_message())
