import requests
import json

url = "https://awake-murex.vercel.app/api/generate-site"
data = {
    "businessName": "Justice Legal",
    "businessType": "law",
    "location": "New York",
    "services": "Corporate law, litigation, family law",
    "style": "professional"
}

try:
    print(f"Connecting to: {url}")
    response = requests.post(url, json=data, timeout=30)
    print(f"Status: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=4)}")
    except:
        print(f"Response Text (Full): {response.text}")
except Exception as e:
    print(f"Error: {e}")
