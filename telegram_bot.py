"""Owner-only Telegram tap menu for paper gold signals; no MT5 execution."""
import os
import time
import requests
import json
import hashlib
import hmac
import pandas as pd
from datetime import datetime, timezone
from threading import Thread
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
SECRET = hashlib.sha256(TOKEN.encode()).hexdigest()
HOOK = '/updates/' + SECRET[:20]
FEED_KEY = os.environ.get('MT5_FEED_KEY', '')
latest_gold = {'bars': None, 'received': 0, 'tick_time': 0}

class DashboardHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/mt5/feed':
            if not FEED_KEY or not hmac.compare_digest(self.headers.get('X-Feed-Key', ''), FEED_KEY):
                self.send_error(403)
                return
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n < 1 or n > 100000:
                    self.send_error(400)
                    return
                data = json.loads(self.rfile.read(n))
                bars = data['bars']
                if len(bars) < 52 or len(bars) > 200 or any(not all(k in bar for k in ('open','high','low','close')) for bar in bars):
                    self.send_error(400)
                    return
                latest_gold.update({'bars': bars, 'received': time.time(), 'tick_time': int(data.get('tick_time',0))})
                self.send_response(200)
                self.end_headers()
            except Exception:
                self.send_error(400)
            return
        if self.path != HOOK or self.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET:
            self.send_error(403)
            return
        n = int(self.headers.get('Content-Length', '0'))
        if n < 1 or n > 65536:
            self.send_error(400)
            return
        data = json.loads(self.rfile.read(n))
        self.send_response(200)
        self.end_headers()
        Thread(target=process_update, args=(data,), daemon=True).start()

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
        return '📡 Bot online. Paper signals: ' + ('ON' if enabled else 'OFF') + '. MT5 feed: ' + ('FRESH' if latest_gold['bars'] and time.time()-latest_gold['received'] < 180 else 'WAITING') + '. Auto trading: OFF.'
    if action == "signal":
        if not enabled:
            return "Paper signals paused. Tap Start paper signals first."
        try:
            if not latest_gold['bars'] or time.time() - latest_gold['received'] > 180:
                return 'MT5 gold feed unavailable or stale. No signal generated.'
            df = pd.DataFrame(latest_gold['bars'])
            return '📊 MT5 demo paper signal: ' + str(signal(df))
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

def process_update(update):
    try:
        callback = update.get('callback_query')
        if callback:
            if str(callback.get('from', {}).get('id', '')) != OWNER:
                api('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': 'Not authorized'})
                return
            api('answerCallbackQuery', {'callback_query_id': callback['id']})
            chat = callback.get('message', {}).get('chat', {}).get('id')
            if chat:
                reply(chat, handle(callback.get('data', 'menu')))
            return
        msg = update.get('message') or {}
        if str(msg.get('from', {}).get('id', '')) != OWNER:
            return
        cmd = str(msg.get('text', '')).split()[0].split('@')[0].lstrip('/').lower() if msg.get('text') else 'menu'
        reply(msg['chat']['id'], handle(cmd))
    except Exception as exc:
        print('Update error:', type(exc).__name__, flush=True)

while True:
    try:
        api('setWebhook', {'url': DASHBOARD_URL.rstrip('/') + HOOK, 'secret_token': SECRET, 'allowed_updates': ['message', 'callback_query']})
        print('Webhook ready', flush=True)
        break
    except Exception as exc:
        print('Webhook setup error:', type(exc).__name__, flush=True)
        time.sleep(10)
while True:
    time.sleep(3600)
