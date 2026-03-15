import requests
import json
import time

API_BASE = "http://127.0.0.1:5000"

def test_flow():
    # 1. Start Generation
    data = {
        "businessName": "Multi Test",
        "businessType": "consulting",
        "location": "London",
        "services": "Strategy, Planning, Growth",
        "style": "modern",
        "colors": ["#112233", "#445566", "#778899"]
    }
    
    print("Starting generation...")
    res = requests.post(f"{API_BASE}/api/generate-site", json=data)
    if res.status_code != 200:
        print(f"Error starting: {res.text}")
        return
        
    slug = res.json()["slug"]
    print(f"Slug: {slug}")
    
    # 2. Poll Status
    while True:
        status_res = requests.get(f"{API_BASE}/api/status/{slug}")
        status_data = status_res.json()
        print(f"Status: {status_data['status']} - {status_data['message']}")
        
        if status_data["status"] == "WAITING_FOR_SELECTION":
            print("Successfully reached selection state!")
            print(f"Variations: {len(status_data['variations'])}")
            break
        elif status_data["status"] == "FAILED":
            print("Generation failed")
            return
            
        time.sleep(5)
        
    # 3. Select Design
    print("Selecting design 1...")
    sel_res = requests.post(f"{API_BASE}/api/select-design", json={"slug": slug, "designIndex": 1})
    if sel_res.status_code == 200:
        print(f"Final Preview: {sel_res.json()['previewUrl']}")
    else:
        print(f"Selection failed: {sel_res.text}")

if __name__ == "__main__":
    test_flow()
