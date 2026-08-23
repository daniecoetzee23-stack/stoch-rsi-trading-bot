from flask import Flask, render_template, request, jsonify
from iqoptionapi.stable_api import IQ_Option
import os

app = Flask(__name__)

api = None
is_running = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login_account():
    global api
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({"status": "error", "message": "Please enter email and password"})
    
    try:
        print(f"Attempting login for: {email}")
        api = IQ_Option(email, password)
        check, reason = api.connect()
        
        if check:
            balance = api.get_balance()
            print(f"Login successful! Balance: {balance}")
            return jsonify({"status": "success", "message": "Logged in successfully!", "balance": balance})
        else:
            print(f"Login failed: {reason}")
            return jsonify({"status": "error", "message": str(reason)})
    except Exception as e:
        print(f"Login Exception occurred: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/start', methods=['POST'])
def start_bot():
    global is_running, api
    if not api or not api.check_connect():
        return jsonify({"status": "error", "message": "Please log in first!"})
    
    is_running = True
    return jsonify({"status": "success", "message": "Bot started!"})

@app.route('/stop', methods=['POST'])
def stop_bot():
    global is_running
    is_running = False
    return jsonify({"status": "success", "message": "Bot stopped!"})

@app.route('/stats')
def stats():
    global api, is_running
    try:
        if api and api.check_connect():
            balance = api.get_balance()
            status_text = "Running" if is_running else "Stopped (Logged In)"
            return jsonify({"status": status_text, "balance": balance})
    except Exception:
        pass
    return jsonify({"status": "Stopped", "balance": 0.00})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
