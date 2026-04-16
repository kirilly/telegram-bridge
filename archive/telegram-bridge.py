#!/usr/bin/env python3
"""
Telegram Bridge — dumb I/O layer between Telegram and the filesystem.
The bridge polls Telegram, writes incoming messages to inbox/, reads
outbox/ for replies, and sends them back. A Claude dispatcher session
(interactive, visible to you) handles the actual work.

Usage:
    python telegram-bridge.py              # run bridge
    python telegram-bridge.py --dry-run    # validate config + bot token, exit

Inbox format (one JSON file per message):
    inbox/<update_id>.json = {chat_id, sender_id, sender_name, text, message_id, timestamp}

Outbox format (one JSON file per reply, bridge deletes after sending):
    outbox/<any-name>.json = {chat_id, text, reply_to_message_id?}
"""

import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "bridge-config.json"
INBOX_DIR = SCRIPT_DIR / "inbox"
OUTBOX_DIR = SCRIPT_DIR / "outbox"

running = True


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def tg_api(token, method, params=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = json.dumps(params).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def send_message(token, chat_id, text, reply_to=None):
    """Send message, chunking at 4096 chars (Telegram limit)."""
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    for i, chunk in enumerate(chunks):
        params = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_to and i == 0:
            params["reply_to_message_id"] = reply_to
        try:
            tg_api(token, "sendMessage", params)
        except urllib.error.HTTPError:
            params.pop("parse_mode", None)
            tg_api(token, "sendMessage", params)


def process_outbox(token):
    """Send any pending outbox messages and delete the files."""
    if not OUTBOX_DIR.exists():
        return
    for f in sorted(OUTBOX_DIR.glob("*.json")):
        try:
            msg = json.loads(f.read_text())
            send_message(
                token,
                msg["chat_id"],
                msg["text"],
                reply_to=msg.get("reply_to_message_id"),
            )
            logging.info("sent outbox: %s (%d chars)", f.name, len(msg["text"]))
            f.unlink()
        except Exception as e:
            logging.error("outbox error %s: %s", f.name, e)


def main():
    global running

    config = load_config()

    log_file = SCRIPT_DIR / config.get("log_file", "bridge.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    token_env = config.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env)
    if not token:
        logging.error("Missing env var %s", token_env)
        sys.exit(1)

    allowed = set(config.get("allowed_users", []))
    if not allowed:
        logging.error("No allowed_users in config — nobody can use the bot")
        sys.exit(1)

    me = tg_api(token, "getMe")
    bot_name = me["result"]["username"]
    logging.info("Bot: @%s", bot_name)

    INBOX_DIR.mkdir(exist_ok=True)
    OUTBOX_DIR.mkdir(exist_ok=True)

    if "--dry-run" in sys.argv:
        logging.info("Ready (dry-run). Allowed users: %s", allowed)
        logging.info("Inbox: %s", INBOX_DIR)
        logging.info("Outbox: %s", OUTBOX_DIR)
        return

    poll_timeout = config.get("poll_timeout", 30)
    offset = 0

    def shutdown(signum, frame):
        global running
        logging.info("Shutting down (signal %s)", signum)
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logging.info("Polling started. Allowed users: %s", allowed)
    logging.info("Inbox: %s", INBOX_DIR)
    logging.info("Outbox: %s", OUTBOX_DIR)

    while running:
        # 1. Check outbox for replies to send
        try:
            process_outbox(token)
        except Exception as e:
            logging.error("Outbox sweep error: %s", e)

        # 2. Poll Telegram for new messages
        try:
            updates = tg_api(token, "getUpdates", {
                "offset": offset,
                "timeout": poll_timeout,
                "allowed_updates": ["message"],
            })
        except (urllib.error.URLError, OSError) as e:
            logging.warning("Poll error: %s", e)
            time.sleep(5)
            continue

        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message")
            if not msg or not msg.get("text"):
                continue

            sender_id = msg["from"]["id"]
            sender_name = msg["from"].get("username", str(sender_id))
            chat_id = msg["chat"]["id"]
            text = msg["text"]

            if sender_id not in allowed:
                logging.info("blocked: %d (%s)", sender_id, sender_name)
                continue

            # Write to inbox for the dispatcher to pick up
            inbox_file = INBOX_DIR / f"{update['update_id']}.json"
            inbox_file.write_text(json.dumps({
                "chat_id": chat_id,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "text": text,
                "message_id": msg["message_id"],
                "timestamp": msg.get("date", 0),
            }, indent=2))
            logging.info("inbox: %s from %s: %s", inbox_file.name, sender_name, text[:80])

    logging.info("Stopped.")


if __name__ == "__main__":
    main()
