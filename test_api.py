import requests
import json

url = "http://localhost:5000/api/generate-site"
data = {
    "businessName": "Justice Legal",
    "businessType": "law",
    "location": "New York",
    "style": "professional",
    "services": "Corporate law, litigation"
}

try:
    response = requests.post(url, json=data)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
