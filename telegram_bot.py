"""Owner-only Telegram tap menu for paper gold signals; no MT5 execution."""
import os
import time
import requests
import json
import hashlib
import hmac
from urllib.parse import parse_qsl
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
CONTROL_KEY = os.environ.get('MT5_CONTROL_KEY', '')
control = {'state': 'PAUSE', 'updated': time.time(), 'ack': 0, 'paper_state': 'PAUSE'}
latest_gold = {'bars': None, 'received': 0, 'tick_time': 0, 'account': None, 'terminal_connected': False, 'account_received': 0, 'trading': None}

class DashboardHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/mt5/control/ack':
            if not CONTROL_KEY or not hmac.compare_digest(self.headers.get('X-Control-Key', ''), CONTROL_KEY):
                self.send_error(403)
                return
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n < 1 or n > 1024:
                    self.send_error(400)
                    return
                payload = json.loads(self.rfile.read(n))
                if payload.get('state') == control['state'] and payload.get('updated') == control['updated']:
                    control['ack'] = time.time()
                self.send_response(200)
                self.end_headers()
            except Exception:
                self.send_error(400)
            return
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
                account = data.get('account')
                if account and isinstance(account.get('balance'), (int, float)) and account.get('currency'):
                    latest_gold.update({'account': {'balance': account['balance'], 'currency': str(account['currency'])[:8]}, 'terminal_connected': True, 'account_received': time.time()})
                trading = data.get('trading')
                if isinstance(trading, dict):
                    latest_gold['trading'] = trading
                latest_gold.update({'bars': bars, 'received': time.time(), 'tick_time': int(data.get('tick_time',0))})
                if data.get('demo_ack_updated') == control['updated'] and control['state'] == 'START_DEMO':
                    control['ack'] = time.time()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'paper_state':control['paper_state'], 'demo_state':control['state'], 'control_updated':control['updated']}).encode())
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
        if self.path.split('?')[0] == '/mt5/control':
            if not CONTROL_KEY or not hmac.compare_digest(self.headers.get('X-Control-Key', ''), CONTROL_KEY):
                self.send_error(403)
                return
            body = json.dumps(control).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split('?')[0] == '/api/account':
            raw = self.headers.get('X-Telegram-Init-Data', '')
            try:
                fields = dict(parse_qsl(raw, keep_blank_values=True))
                supplied = fields.pop('hash', '')
                check = '\n'.join(k+'='+v for k,v in sorted(fields.items()))
                secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
                expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
                user = json.loads(fields.get('user', '{}'))
                authorized = hmac.compare_digest(supplied, expected) and str(user.get('id')) == OWNER and abs(time.time()-int(fields.get('auth_date','0'))) < 86400
            except Exception:
                authorized = False
            if not authorized:
                self.send_error(403)
                return
            active = latest_gold['terminal_connected'] and time.time()-latest_gold['account_received'] < 180
            response = {'connected': bool(active), 'account': latest_gold['account'] if active else None, 'demo_control': control['state'], 'vps_acknowledged': bool(control['state'] == 'START_DEMO' and control['ack'] >= control['updated']), 'paper_signals': bool(enabled), 'trading': latest_gold['trading'] if active else None}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            return
        if self.path.split('?')[0] == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            # Public endpoint exposes connection flags only, never private account balances.
            self.wfile.write(json.dumps({'feed_fresh': bool(latest_gold['bars']) and time.time()-latest_gold['received'] < 180 and time.time()-latest_gold['tick_time'] < 3600, 'account_connected': latest_gold['terminal_connected'] and time.time()-latest_gold['account_received'] < 180, 'execution': 'OFF'}).encode())
            return
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
        [{"text": "▶️ Start auto demo", "callback_data": "start"},
         {"text": "⏸ Pause", "callback_data": "pause"}],
        [{"text": "🧪 Restart MT5 demo", "callback_data": "demo_start"},
         {"text": "🛡 Demo control status", "callback_data": "demo_status"}],
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

def live_summary():
    now = time.time()
    feed = bool(latest_gold['bars']) and now-latest_gold['received'] < 180 and 0 <= now-latest_gold['tick_time'] < 300
    account = latest_gold['account'] if now-latest_gold['account_received'] < 180 else None
    balance = (f"{account['currency']} {float(account['balance']):,.2f}" if account else 'Waiting for fresh MT5 data')
    ack = control['state'] == 'START_DEMO' and control['ack'] >= control['updated']
    demo = ('START acknowledged by VPS' if ack else 'START requested; awaiting VPS' if control['state']=='START_DEMO' else 'PAUSED')
    try:
        raw = signal(pd.DataFrame(latest_gold['bars'])) if feed else None
        direction = str(raw.get('signal', 'WAIT')) if isinstance(raw, dict) else 'Unavailable'
        price = float(raw['price']) if isinstance(raw, dict) and raw.get('price') is not None else None
        signal_line = direction + (f' | Gold: {price:,.2f}' if price is not None else '')
    except Exception:
        signal_line = 'Unavailable'
    return ('📊 GOLD BOT LIVE OVERVIEW\n'
            + 'Paper signals: ' + ('ON' if enabled else 'OFF') + '\n'
            + 'Demo control: ' + demo + '\n'
            + 'Market feed: ' + ('FRESH' if feed else 'WAITING / STALE') + '\n'
            + 'MT5 balance: ' + balance + '\n'
            + 'Gold signal: ' + signal_line + '\n'
            + 'Open trades / P&L: ' + ((str(latest_gold['trading'].get('open_count',0)) + ' / ' + format(float(latest_gold['trading'].get('floating_pl',0)), '+,.2f')) if latest_gold.get('trading') else 'Waiting for MT5 telemetry') + '\n'
            + 'Risk setting: 0.5% per trade; verify executor safeguards\n'
            + 'Note: VPS acknowledgement is not proof an order executed.')

def handle(action):
    global enabled
    if action == "start":
        enabled = True
        control['paper_state'] = 'START'
        control['state'] = 'START_DEMO'
        control['updated'] = time.time()
        control['ack'] = 0
        return "▶️ Automatic DEMO trading requested. Scanning begins on the next VPS cycle; trades require valid signals and risk checks.\n\n" + live_summary()
    if action in ("stop", "pause"):
        enabled = False
        control['paper_state'] = 'PAUSE'
        control["state"] = "PAUSE"
        control["updated"] = time.time()
        control["ack"] = 0
        return "⏸ Paper signals paused. MT5 demo pause requested; existing trades are not closed."
    if action == "demo_start":
        enabled = True
        control['paper_state'] = 'START'
        control['state'] = 'START_DEMO'
        control['updated'] = time.time()
        control['ack'] = 0
        return '🧪 Demo start requested.\n\n' + live_summary()
    if action == "demo_status":
        return 'MT5 demo control: ' + control['state'] + ('. VPS acknowledged.' if control['ack'] >= control['updated'] else '. Awaiting VPS acknowledgement.')
    if action == "status":
        return live_summary()
    if action == "signal":
        if not enabled:
            return "Paper signals paused. Tap Start paper signals first."
        try:
            if not latest_gold['bars'] or time.time() - latest_gold['received'] > 180 or time.time() - latest_gold['tick_time'] > 3600:
                return 'MT5 gold feed unavailable or stale. No signal generated.'
            df = pd.DataFrame(latest_gold['bars'])
            raw = signal(df)
            return '📊 Gold signal: ' + str(raw.get('signal','WAIT')) + ((' | Price: ' + format(float(raw['price']), ',.2f')) if raw.get('price') is not None else '')
        except Exception as exc:
            return "Market signal unavailable: " + str(exc)[:200]
    return live_summary() + "\n\nChoose a button below."

# Make slash commands visible in Telegram's command picker.
try:
    api("setMyCommands", {"commands": [
        {"command": "menu", "description": "Open tap control panel"},
        {"command": "start", "description": "Start automatic demo trading"},
        {"command": "pause", "description": "Pause paper signals"},
        {"command": "status", "description": "Check bot status"},
        {"command": "signal", "description": "Check gold signal"},
        {"command": "stop", "description": "Stop paper signals"},
        {"command": "demo_status", "description": "Check VPS demo connection"},
        {"command": "demo_start", "description": "Request MT5 demo start"}
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
# Notify the owner once when an observed live gold feed stops updating.
# A stale feed can also mean a VPS/network failure, so do not claim a confirmed exchange close.
def market_watch():
    saw_live = False
    notified = False
    while True:
        try:
            now = time.time()
            heartbeat = bool(latest_gold['bars']) and now - latest_gold['received'] < 180
            tick_live = heartbeat and latest_gold['tick_time'] > 0 and 0 <= now - latest_gold['tick_time'] < 300
            if tick_live:
                saw_live = True
                notified = False
            elif saw_live and not notified and (not heartbeat or now - latest_gold['tick_time'] >= 300):
                api('sendMessage', {'chat_id': OWNER, 'text': '🔔 Gold market update: XAUUSD live prices have stopped updating. The market may be closed, or the VPS/feed may be disconnected. Goldvvbot will not generate signals on stale prices.'})
                notified = True
        except Exception as exc:
            print('Market watch error:', type(exc).__name__, flush=True)
        time.sleep(60)

Thread(target=market_watch, daemon=True).start()
while True:
    time.sleep(3600)
