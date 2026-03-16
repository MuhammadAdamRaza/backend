"""
Quick script to check if Gemini AI is working.
Run from backend folder: python check_ai.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("FAIL: GEMINI_API_KEY not set in .env")
    exit(1)

print("GEMINI_API_KEY is set.")
print("Calling Gemini API...")

try:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    # Try common model names (Google sometimes renames)
    for model_name in ["gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-pro"]:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Reply with exactly: AI is working")
            text = (response.text or "").strip()
            if "working" in text.lower() or len(text) > 0:
                print("SUCCESS: AI responded (model=%s):" % model_name, text[:80])
                break
        except Exception as inner:
            if "404" in str(inner) or "not found" in str(inner).lower():
                continue
            raise
    else:
        print("FAIL: No working model found. Try setting GEMINI_MODEL in .env (e.g. gemini-pro)")
        exit(1)
except Exception as e:
    print("FAIL:", type(e).__name__, str(e))
    if "API_KEY" in str(e) or "403" in str(e):
        print("Tip: Check your GEMINI_API_KEY at https://aistudio.google.com/apikey")
    elif "404" in str(e) or "not found" in str(e).lower():
        print("Tip: Add to .env: GEMINI_MODEL=gemini-pro (or check Google AI for current model names)")
    exit(1)
