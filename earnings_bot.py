import os
import json
import requests

from earnings_calendar import check_nasdaq_earnings


TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = "data/sent_alerts.json"


def load_sent_alerts():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r") as file:
            return json.load(file)

    except Exception:
        return {}


def save_sent_alerts(data):
    os.makedirs("data", exist_ok=True)

    with open(STATE_FILE, "w") as file:
        json.dump(data, file, indent=2)


def send_telegram(message):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=10
        )

        result = response.json()

        return result.get("ok", False)

    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def main():

    sent_alerts = load_sent_alerts()

    earnings = check_nasdaq_earnings()

    if not earnings:
        print("No earnings found.")
        return


    updated = False


    for company in earnings:

        try:
            symbol = company.get("symbol")
            earnings_date = company.get("date")

            alert_id = f"{symbol}_{earnings_date}"


            if alert_id in sent_alerts:
                print(f"Already sent: {alert_id}")
                continue


            message = f"""
${symbol} Earnings Alert

Earnings Date:
{earnings_date}

NASDAQ
"""


            success = send_telegram(message.strip())


            if success:
                sent_alerts[alert_id] = True
                updated = True
                print(f"Sent successfully: {alert_id}")

            else:
                print(f"Telegram failed: {alert_id}")


        except Exception as e:
            print(f"Error processing company: {e}")


    if updated:
        save_sent_alerts(sent_alerts)
        print("State updated.")


if name == "main":
    main()
