"""Release notifications."""

from __future__ import annotations

import http.client
import urllib.parse

from .common import error

def notify_telegram(args: argparse.Namespace) -> None:
    if not args.bot_token or not args.chat_id:
        print("Telegram notification skipped: BOT_TOKEN and CHAT_ID are required.")
        return
    release_url = (
        f"https://github.com/{args.repository}/releases/tag/{args.release_tag}"
    )
    data = urllib.parse.urlencode(
        {
            "chat_id": args.chat_id,
            "disable_web_page_preview": "true",
            "text": f"{args.release_name}\nTag: {args.release_tag}\nRelease: {release_url}",
        }
    ).encode()
    endpoint = f"/bot{args.bot_token}/sendMessage"
    connection = http.client.HTTPSConnection("api.telegram.org", timeout=30)
    try:
        connection.request(
            "POST",
            endpoint,
            body=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            error(f"Telegram request failed: HTTP {response.status}")
    except OSError as exc:
        error(f"Telegram request failed: {exc}")
    finally:
        connection.close()


