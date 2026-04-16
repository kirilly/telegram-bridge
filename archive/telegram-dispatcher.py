#!/usr/bin/env python3
"""
Telegram Dispatcher — single process, session-aware, no API cost.
Polls Telegram, dispatches to claude CLI (--resume for session persistence),
sends responses back. Best of nanoclaw + harness.

Usage:
    python telegram-dispatcher.py              # run dispatcher
    python telegram-dispatcher.py --dry-run    # validate config + bot, exit
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "bridge-config.json"

running = True
session_id = None


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
    if not text.strip():
        text = "(empty response)"
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


def parse_stream_json(raw):
    """Extract text content from claude --output-format stream-json."""
    texts = []
    for line in raw.strip().split("\n"):
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant":
                for c in obj.get("message", {}).get("content", []):
                    if c.get("type") == "text":
                        texts.append(c["text"])
        except (json.JSONDecodeError, KeyError):
            continue
    return "".join(texts)


def extract_session_id(raw):
    """Extract session_id from stream-json output."""
    for line in raw.strip().split("\n"):
        try:
            obj = json.loads(line)
            if obj.get("type") == "result" and obj.get("session_id"):
                return obj["session_id"]
            if obj.get("type") == "system" and obj.get("session_id"):
                return obj["session_id"]
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def dispatch(message_text, config):
    """Send message to claude CLI, maintain session."""
    global session_id

    cmd = [
        "claude", "-p", message_text,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "auto",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        # Extract session ID for future resume
        new_sid = extract_session_id(result.stdout)
        if new_sid:
            session_id = new_sid

        text = parse_stream_json(result.stdout)
        if text.strip():
            return text.strip()
        if result.stderr.strip():
            logging.error("claude stderr: %s", result.stderr[:500])
        return "Error: Claude did not return a response."
    except subprocess.TimeoutExpired:
        return "Error: Claude timed out (120s)."
    except FileNotFoundError:
        return "Error: claude CLI not found in PATH."


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

    if "--dry-run" in sys.argv:
        logging.info("Ready (dry-run). Allowed users: %s", allowed)
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

    while running:
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

            logging.info("msg from %s: %s", sender_name, text[:80])

            response = dispatch(text, config)
            send_message(token, chat_id, response, reply_to=msg["message_id"])
            logging.info("replied (%d chars) session=%s", len(response), session_id)

    logging.info("Stopped.")


if __name__ == "__main__":
    main()
