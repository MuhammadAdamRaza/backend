import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

print(f"Using API Key: {api_key[:10]}...")
print(f"Using Model: {model_name}")

if not api_key:
    print("ERROR: GEMINI_API_KEY is not set.")
    exit(1)

genai.configure(api_key=api_key)

try:
    model = genai.GenerativeModel(model_name)
    response = model.generate_content("Hello")
    print("SUCCESS!")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()
