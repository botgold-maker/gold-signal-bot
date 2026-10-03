"""Telegram interface for paper-only gold signal monitoring. No MT5 trade control."""
import os
import time
import requests
from main import fetch, signal

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER = os.environ.get("TELEGRAM_OWNER_ID", "")
BASE = "https://api.telegram.org/bot" + TOKEN + "/"
if not TOKEN or not OWNER:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID privately in Railway")

enabled = False  # Only enables PAPER signal checks; never broker execution.
offset = None

def reply(chat, message):
    requests.post(BASE + "sendMessage", json={"chat_id": chat, "text": message}, timeout=15).raise_for_status()

def handle(chat, text):
    global enabled
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    if cmd == "/start":
        enabled = True
        return "Paper signals enabled. No trades are sent to MT5."
    if cmd in ("/stop", "/pause"):
        enabled = False
        return "Paper signals paused. This does NOT stop MT5 or close trades."
    if cmd == "/status":
        return "Railway Telegram bridge online. Paper signals: " + ("ON" if enabled else "OFF") + ". MT5 control: NOT CONNECTED."
    if cmd == "/signal":
        if not enabled:
            return "Paper signals are paused. Use /start to enable."
        try:
            return "Paper-only gold signal: " + str(signal(fetch()))
        except Exception as exc:
            return "Market signal unavailable: " + str(exc)[:200]
    return "Commands: /start /stop /pause /status /signal. All are PAPER ONLY."

while True:
    try:
        params = {"timeout": 20}
        if offset is not None:
            params["offset"] = offset
        response = requests.get(BASE + "getUpdates", params=params, timeout=30)
        response.raise_for_status()
        for update in response.json().get("result", []):
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            if chat != OWNER:
                continue
            reply(chat, handle(chat, str(msg.get("text", ""))))
    except Exception as exc:
        print("Telegram polling error:", type(exc).__name__, flush=True)
        time.sleep(5)
