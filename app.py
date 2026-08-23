import time
import threading
import pandas as pd
from flask import Flask, render_template_string, jsonify
from iqoptionapi.stable_api import IQ_Option
from datetime import datetime

app = Flask(__name__)
app.secret_key = "stochastic_rsi_bot_secret"

# --- IQ Option Config ---
EMAIL = "landiqcoetzee123@gmail.com"
PASSWORD = "Caitlynn@2013"
PRACTICE_ACCOUNT = True
PAIRS = ["EURUSD-OTC", "EURGBP-OTC", "USDCHF-OTC", "GBPUSD-OTC", "AUDCAD-OTC"]

# --- Bot State & Stats ---
bot_running = False
bot_stats = {
    "status": "Stopped",
    "balance": 0.0,
    "profit": 0.0,
    "wins": 0,
    "losses": 0,
    "win_rate": 0.0,
    "logs": ["[System] Interface loaded. Ready to start..."]
}

Iq = None

def log_message(msg):
    timestamp = time.strftime('%H:%M:%S')
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    bot_stats["logs"].insert(0, formatted)
    if len(bot_stats["logs"]) > 50:
        bot_stats["logs"].pop()

def ensure_connection(iq_client):
    try:
        if not iq_client.check_connect():
            log_message("🔄 Reconnecting to IQ Option API...")
            iq_client.connect()
            time.sleep(2)
    except Exception:
        try:
            iq_client.connect()
            time.sleep(2)
        except Exception:
            pass

def calculate_indicators(iq_client, pair):
    ensure_connection(iq_client)
    try:
        candles = iq_client.get_candles(pair, 60, 120, time.time())
    except Exception as e:
        return None

    if not candles or len(candles) < 30:
        return None

    df = pd.DataFrame(candles)
    if 'min' in df.columns:
        df.rename(columns={'min': 'low'}, inplace=True)
    if 'max' in df.columns:
        df.rename(columns={'max': 'high'}, inplace=True)

    for col in ['open', 'close', 'high', 'low']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['open', 'high', 'low', 'close']).reset_index(drop=True)

    try:
        low_min = df['low'].rolling(window=8).min()
        high_max = df['high'].rolling(window=8).max()
        df['STOCH_K'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
        df['STOCH_D'] = df['STOCH_K'].rolling(window=3).mean()
        df['STOCH_K'] = df['STOCH_K'].rolling(window=3).mean()
    except Exception:
        return None

    try:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
    except Exception:
        return None

    df = df.dropna(subset=['STOCH_K', 'STOCH_D', 'RSI']).reset_index(drop=True)
    if len(df) < 3:
        return None

    return df

def stoch_rsi_signal(df):
    if len(df) < 3:
        return "hold", "Insufficient data"

    try:
        current_k = float(df['STOCH_K'].iloc[-1])
        previous_k = float(df['STOCH_K'].iloc[-2])
        current_d = float(df['STOCH_D'].iloc[-1])
        previous_d = float(df['STOCH_D'].iloc[-2])
        current_rsi = float(df['RSI'].iloc[-1])
        previous_rsi = float(df['RSI'].iloc[-2])
    except Exception:
        return "hold", "Calculation error"

    note = f"Stoch K: {current_k:.1f} | RSI: {current_rsi:.1f}"

    buy_signal = (
        current_k > current_d and
        previous_k <= previous_d and
        current_k < 20 and
        current_rsi < 30 and
        current_rsi > previous_rsi
    )

    sell_signal = (
        current_k < current_d and
        previous_k >= previous_d and
        current_k > 80 and
        current_rsi > 70 and
        current_rsi < previous_rsi
    )

    if buy_signal:
        return "call", f"Strong Stoch Crossover + RSI Oversold | {note}"
    elif sell_signal:
        return "put", f"Strong Stoch Crossover + RSI Overbought | {note}"

    return "hold", f"Neutral zone | {note}"

def trading_engine():
    global bot_running, bot_stats, Iq
    
    log_message("Connecting to IQ Option...")
    Iq = IQ_Option(EMAIL, PASSWORD)
    Iq.connect()

    if not Iq.check_connect():
        log_message("❌ Connection failed!")
        bot_running = False
        bot_stats["status"] = "Stopped"
        return

    Iq.change_balance("PRACTICE" if PRACTICE_ACCOUNT else "REAL")
    log_message("Connected successfully! Starting market scan...")

    initial_balance = Iq.get_balance()
    bot_stats["balance"] = initial_balance
    bot_stats["status"] = "Running"

    BASE_STAKE = 2.0
    current_stake = BASE_STAKE
    MARTINGALE_MULTIPLIER = 2.0
    MAX_MARTINGALE_STEPS = 3
    consecutive_losses = 0
    active_recovery_pair = None
    active_recovery_decision = None

    while bot_running:
        target_pair = None
        target_decision = None

        if consecutive_losses > 0 and active_recovery_pair and active_recovery_decision:
            log_message(f"🔄 Martingale Step {consecutive_losses}: Re-entering {active_recovery_pair} with ${current_stake:.2f}")
            target_pair = active_recovery_pair
            target_decision = active_recovery_decision
        else:
            for pair in PAIRS:
                if not bot_running:
                    break
                ensure_connection(Iq)
                df = calculate_indicators(Iq, pair)
                if df is not None:
                    decision, note = stoch_rsi_signal(df)
                    log_message(f"[{pair}] {decision.upper()} ({note})")
                    if decision != "hold":
                        target_pair = pair
                        target_decision = decision
                        log_message(f"🎯 Signal found on {pair}: {decision.upper()}!")
                        break
                time.sleep(1.0)

        if not target_pair or not target_decision or not bot_running:
            time.sleep(3)
            continue

        try:
            ensure_connection(Iq)
            stake = max(1.0, float(current_stake))
            balance_before = Iq.get_balance()
            
            check, trade_id = Iq.buy_digital_spot(target_pair, stake, target_decision, 1)
            if not check or not trade_id:
                check_bin, trade_id_bin = Iq.buy(stake, target_pair, target_decision, 1)
                if check_bin and trade_id_bin:
                    trade_id = trade_id_bin
                else:
                    log_message("❗ Order rejected. Skipping...")
                    continue

            log_message(f"⏳ Order confirmed on {target_pair} (${stake:.2f}). Waiting 1 min...")
            time.sleep(63)
            time.sleep(2)

            balance_after = Iq.get_balance()
            trade_pnl = round(balance_after - balance_before, 2)

            if trade_pnl > 0:
                bot_stats["wins"] += 1
                consecutive_losses = 0
                current_stake = BASE_STAKE
                active_recovery_pair = None
                active_recovery_decision = None
                log_message(f"✅ Trade Won! +${trade_pnl:.2f} (Reset stake)")
            elif trade_pnl < 0:
                bot_stats["losses"] += 1
                consecutive_losses += 1
                if consecutive_losses <= MAX_MARTINGALE_STEPS:
                    current_stake = round(current_stake * MARTINGALE_MULTIPLIER, 2)
                    active_recovery_pair = target_pair
                    active_recovery_decision = target_decision
                    log_message(f"❌ Trade Lost! Martingale step {consecutive_losses} -> Next: ${current_stake}")
                else:
                    log_message("❌ Max Martingale reached. Resetting stake.")
                    consecutive_losses = 0
                    current_stake = BASE_STAKE
                    active_recovery_pair = None
                    active_recovery_decision = None
            else:
                log_message("⚠️ Trade resulted in a Draw.")

            bot_stats["balance"] = balance_after
            bot_stats["profit"] = round(balance_after - initial_balance, 2)
            
            decisive = bot_stats["wins"] + bot_stats["losses"]
            if decisive > 0:
                bot_stats["win_rate"] = round((bot_stats["wins"] / decisive) * 100, 1)

        except Exception as e:
            log_message(f"Runtime error: {e}")

        time.sleep(1)

    bot_stats["status"] = "Stopped"

# --- Mobile-Responsive UI with Auto-Polling ---
UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloud Trading Bot</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 text-gray-100 font-sans p-4">
    <div class="max-w-md mx-auto space-y-4">
        <div class="bg-gray-900 p-4 rounded-2xl border border-gray-800 text-center shadow-lg">
            <h1 class="text-xl font-bold text-blue-400">🤖 Stoch + RSI Cloud Bot</h1>
            <p class="text-xs text-gray-400">Live Online Interface</p>
        </div>

        <div class="bg-gray-900 p-4 rounded-2xl border border-gray-800 grid grid-cols-2 gap-4 shadow-lg">
            <div>
                <p class="text-xs text-gray-400">Status</p>
                <p id="status" class="text-base font-bold text-yellow-400">Stopped</p>
            </div>
            <div>
                <p class="text-xs text-gray-400">Balance</p>
                <p id="balance" class="text-base font-bold">$0.00</p>
            </div>
            <div>
                <p class="text-xs text-gray-400">Net Profit</p>
                <p id="profit" class="text-base font-bold">$0.00</p>
            </div>
            <div>
                <p class="text-xs text-gray-400">Win Rate</p>
                <p id="win_rate" class="text-base font-bold">0.0%</p>
            </div>
        </div>

        <div class="flex gap-4">
            <button onclick="startBot()" class="flex-1 bg-green-600 hover:bg-green-500 py-3 rounded-xl font-bold text-sm shadow-lg transition">Start Bot</button>
            <button onclick="stopBot()" class="flex-1 bg-red-600 hover:bg-red-500 py-3 rounded-xl font-bold text-sm shadow-lg transition">Stop Bot</button>
        </div>

        <div class="bg-black p-4 rounded-2xl border border-gray-800 h-64 overflow-y-auto font-mono text-xs text-green-400 shadow-inner" id="logs">
            [System] Loaded interface. Ready...
        </div>
    </div>

    <script>
        function updateStats() {
            fetch('/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('status').innerText = data.status;
                    if(data.status === "Running") {
                        document.getElementById('status').className = "text-base font-bold text-green-400";
                    } else {
                        document.getElementById('status').className = "text-base font-bold text-yellow-400";
                    }
                    document.getElementById('balance').innerText = '$' + data.balance.toFixed(2);
                    document.getElementById('profit').innerText = '$' + data.profit.toFixed(2);
                    document.getElementById('win_rate').innerText = data.win_rate + '% (' + data.wins + 'W / ' + data.losses + 'L)';
                    
                    let logHtml = '';
                    data.logs.forEach(log => { logHtml += log + '<br>'; });
                    document.getElementById('logs').innerHTML = logHtml;
                });
        }

        function startBot() { 
            fetch('/start').then(() => updateStats()); 
        }
        function stopBot() { 
            fetch('/stop').then(() => updateStats()); 
        }

        setInterval(updateStats, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(UI_TEMPLATE)

@app.route('/stats')
def stats():
    return jsonify(bot_stats)

@app.route('/start')
def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        threading.Thread(target=trading_engine, daemon=True).start()
    return "Started"

@app.route('/stop')
def stop_bot():
    global bot_running
    bot_running = False
    return "Stopped"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)