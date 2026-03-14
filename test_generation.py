import requests
import json

# Test the generation API
payload = {
    "businessName": "Test Business",
    "businessType": "business",
    "services": "Web Design, SEO, Marketing",
    "location": "London, UK",
    "style": "modern"
}

try:
    res = requests.post('http://127.0.0.1:5000/api/generate-site', 
                       json=payload, 
                       timeout=120)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
