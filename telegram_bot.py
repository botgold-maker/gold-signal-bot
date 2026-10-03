"""Owner-only Telegram tap menu for paper gold signals; no MT5 execution."""
import os
import time
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from main import fetch, signal

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OWNER = os.environ.get("TELEGRAM_OWNER_ID", "")
BASE = "https://api.telegram.org/bot" + TOKEN + "/"
if not TOKEN or not OWNER:
    raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_ID privately in Railway")

DASHBOARD_URL = 'https://gold-telegram-production.up.railway.app/'

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?')[0] not in ('/', '/health'):
            self.send_error(404)
            return
        content = b'OK' if self.path.startswith('/health') else Path(__file__).with_name('dashboard.html').read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain' if self.path.startswith('/health') else 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

Thread(target=lambda: ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PORT', '8080'))), DashboardHandler).serve_forever(), daemon=True).start()

enabled = False
offset = None

def menu():
    return {"inline_keyboard": [
        [{"text": "💎 Open Goldvvbot Dashboard", "web_app": {"url": DASHBOARD_URL}}],
        [{"text": "▶️ Start paper signals", "callback_data": "start"},
         {"text": "⏸ Pause", "callback_data": "pause"}],
        [{"text": "📊 Gold signal", "callback_data": "signal"},
         {"text": "📡 Status", "callback_data": "status"}],
        [{"text": "🛑 Stop paper signals", "callback_data": "stop"},
         {"text": "🔄 Refresh menu", "callback_data": "menu"}]
    ]}

def api(method, payload):
    r = requests.post(BASE + method, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError("Telegram API request failed")
    return data

def reply(chat, message):
    api("sendMessage", {"chat_id": chat, "text": message, "reply_markup": menu()})

def handle(action):
    global enabled
    if action == "start":
        enabled = True
        return "▶️ Paper signals enabled. No trades are sent to MT5."
    if action in ("stop", "pause"):
        enabled = False
        return "⏸ Paper signals paused. This does NOT stop MT5 or close trades."
    if action == "status":
        return "📡 Bot online. Paper signals: " + ("ON" if enabled else "OFF") + ". MT5: NOT CONNECTED."
    if action == "signal":
        if not enabled:
            return "Paper signals paused. Tap Start paper signals first."
        try:
            return "📊 Paper-only gold signal: " + str(signal(fetch()))
        except Exception as exc:
            return "Market signal unavailable: " + str(exc)[:200]
    return "Gold bot control panel — PAPER ONLY. Choose a button below."

# Make slash commands visible in Telegram's command picker.
try:
    api("setMyCommands", {"commands": [
        {"command": "menu", "description": "Open tap control panel"},
        {"command": "start", "description": "Start paper signals"},
        {"command": "pause", "description": "Pause paper signals"},
        {"command": "status", "description": "Check bot status"},
        {"command": "signal", "description": "Check gold signal"},
        {"command": "stop", "description": "Stop paper signals"}
    ]})
except Exception as exc:
    print("Command menu setup error:", type(exc).__name__, flush=True)

while True:
    try:
        params = {"timeout": 20}
        if offset is not None:
            params["offset"] = offset
        response = requests.get(BASE + "getUpdates", params=params, timeout=30)
        response.raise_for_status()
        for update in response.json().get("result", []):
            offset = update["update_id"] + 1
            callback = update.get("callback_query")
            if callback:
                user_id = str((callback.get("from") or {}).get("id", ""))
                if user_id != OWNER:
                    api("answerCallbackQuery", {"callback_query_id": callback["id"], "text": "Not authorized", "show_alert": True})
                    continue
                api("answerCallbackQuery", {"callback_query_id": callback["id"]})
                chat = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
                if chat:
                    reply(chat, handle(callback.get("data", "menu")))
                continue
            msg = update.get("message") or {}
            if str((msg.get("from") or {}).get("id", "")) != OWNER:
                continue
            chat = str((msg.get("chat") or {}).get("id", ""))
            cmd = str(msg.get("text", "")).split()[0].split("@")[0].lower().lstrip("/") if msg.get("text") else "menu"
            reply(chat, handle(cmd))
    except Exception as exc:
        print("Telegram polling error:", type(exc).__name__, "409 competing poller" if getattr(getattr(exc, "response", None), "status_code", None) == 409 else "request failed", flush=True)
        time.sleep(5)
