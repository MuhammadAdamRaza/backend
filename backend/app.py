from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Hello from Vercel Backend!"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "msg": "minimal app working"})

if __name__ == '__main__':
    app.run()
