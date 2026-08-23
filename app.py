from flask import Flask, render_template, request, jsonify
from iqoptionapi.stable_api import IQ_Option
import os

app = Flask(__name__)

api = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_bot():
    global api
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({"status": "error", "message": "Please enter email and password"})
    
    try:
        api = IQ_Option(email, password)
        check, reason = api.connect()
        
        if check:
            return jsonify({"status": "success", "message": "Connected successfully!"})
        else:
            return jsonify({"status": "error", "message": str(reason)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stats')
def stats():
    global api
    try:
        if api and api.check_connect():
            balance = api.get_balance()
            return jsonify({"status": "Running", "balance": balance})
    except Exception:
        pass
    return jsonify({"status": "Stopped", "balance": 0.00})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
