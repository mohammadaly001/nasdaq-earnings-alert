import os
import sys
import time

import requests

from morning_earnings import create_message
from earnings_preview import create_preview_message

TELEGRAM_MAX_LENGTH = 4096


def _split_message(message: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list:
    """
    Telegram rejects any single message over 4096 characters. Split on
    the "----------------" separators used in create_message() so each
    chunk stays a clean, readable unit instead of cutting a company's
    block in half.
    """
    if len(message) <= max_length:
        return [message]

    blocks = message.split("----------------")
    chunks = []
    current = ""

    for block in blocks:
        candidate = current + block + "----------------"
        if len(candidate) > max_length and current:
            chunks.append(current.strip())
            current = block + "----------------"
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _send_single(token: str, chat_id: str, text: str, retries: int = 3) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except requests.RequestException as e:
            print(f"Network error (attempt {attempt}/{retries}): {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
            continue

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            retry_after = response.json().get("parameters", {}).get("retry_after", 2 ** attempt)
            print(f"Rate limited, waiting {retry_after}s", file=sys.stderr)
            time.sleep(retry_after)
            continue

        if response.status_code == 401:
            raise Exception("Telegram rejected the bot token (401 Unauthorized). Check TELEGRAM_TOKEN.")

        if response.status_code == 400:
            raise Exception(f"Telegram rejected the request (400 Bad Request): {response.text[:300]}")

        print(f"Telegram error {response.status_code} (attempt {attempt}/{retries}): {response.text[:300]}",
              file=sys.stderr)
        time.sleep(2 ** attempt)

    raise Exception(f"Failed to send Telegram message after {retries} attempts")


def send_telegram(message: str) -> list:
    """Returns a list of Telegram API responses, one per chunk sent."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise Exception("Telegram credentials are missing (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID)")

    chunks = _split_message(message)
    results = []

    for i, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            chunk = f"[{i}/{len(chunks)}]\n\n{chunk}"
        results.append(_send_single(token, chat_id, chunk))

    return results


if __name__ == "__main__":
    morning_message = create_message()

    preview_message = create_preview_message()

    if preview_message and preview_message != "No important NASDAQ earnings tomorrow.":
        final_message = (
            morning_message
            + "\n\n----------------\n\n"
            + preview_message
        )
    else:
        final_message = morning_message

    result = send_telegram(final_message)
    print(result)
