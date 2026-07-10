import datetime

from nasdaq100 import NASDAQ100


def get_upcoming_earnings():
    today = datetime.date.today()

    print("Checking earnings for:", today)

    for ticker in NASDAQ100:
        print(f"Checking {ticker}...")


if name == "main":
    get_upcoming_earnings()
