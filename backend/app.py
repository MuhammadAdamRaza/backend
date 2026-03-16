import os
import json
import sys
import shutil
import tempfile
import re
import subprocess
import requests
import datetime
import random
import traceback

from flask import Flask, request, jsonify, send_from_directory, render_template_string, send_file
from flask_cors import CORS
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv

import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# DATABASE CONFIG ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL:
        print("Warning: DATABASE_URL missing → DB features disabled")
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            slug TEXT PRIMARY KEY,
            business_name TEXT,
            business_type TEXT,
            location TEXT,
            services TEXT,
            style TEXT,
            colors TEXT[],
            status TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS variations (
            id SERIAL PRIMARY KEY,
            site_slug TEXT REFERENCES sites(slug) ON DELETE CASCADE,
            variation_index INT,
            html_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS final_sites (
            site_slug TEXT PRIMARY KEY REFERENCES sites(slug) ON DELETE CASCADE,
            html_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        conn.commit()
        print("Database tables checked/created")
    except Exception as e:
        print(f"DB init error (non-fatal): {e}")
    finally:
        cur.close()
        conn.close()

with app.app_context():
    init_db()

# AI CLIENTS ────────────────────────────────────────────────

openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = "gemini-2.5-flash"   # FIXED: use stable model (March 2026)

model = None
if gemini_key:
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(gemini_model_name)
        print(f"Gemini initialized: {gemini_model_name}")
    except Exception as e:
        print(f"Gemini setup failed: {e}")
        model = None

LAST_AI_ERROR = "No AI errors recorded yet"

# PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TEMP_ROOT = tempfile.gettempdir()
GENERATED_DIR = os.path.join(TEMP_ROOT, "generated-ai-sites")
os.makedirs(GENERATED_DIR, exist_ok=True)

# AI GENERATION FUNCTION (improved cleaning)
def generate_custom_site_html(data, variation_index=0):
    global LAST_AI_ERROR
    
    if not model and not client:
        LAST_AI_ERROR = "No AI client available (Gemini or OpenAI key missing)"
        print(LAST_AI_ERROR)
        return None

    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'business')
    location     = data.get('location', 'International')
    services     = data.get('services', '')
    style        = data.get('style', 'modern')
    colors       = data.get('colors', ["#2563eb","#7c3aed","#f8fafc"])

    services_list = [s.strip() for s in services.split(',') if s.strip()]
    if len(services_list) == 0:
        services_list = ["Professional Services", "Expert Solutions", "Quality Results"]

    layout_patterns = [
        "Hero split-screen + staggered services grid",
        "Full-screen hero with floating cards in wave",
        "Minimal giant typography + bento grid",
        "Diagonal dividers + masonry services",
        "Asymmetric layout + horizontal scroll cards",
        "Glassmorphism panels + circular icons",
        "Centered gradient hero + icon tiles"
    ]
    
    selected_layout = layout_patterns[variation_index % len(layout_patterns)]

    prompt = f"""You are a £75,000+ luxury web design lead.

Create ONE completely unique, modern single-page HTML5 landing page for:

Business: {business_name}
Type: {business_type}
Location: {location}
Style preference: {style}
Color palette: Primary {colors[0]}, Secondary {colors[1]}, Accent/BG {colors[2]}

Services: {', '.join(services_list)}

Use this layout style: {selected_layout}

Rules – very strict:
- Return ONLY raw HTML starting with <!DOCTYPE html>
- All CSS inside <style>, all JS inside <script>
- Only external CDNs: Google Fonts + Font Awesome
- No frameworks (no Bootstrap, no Tailwind)
- Mobile-first responsive design
- Real, persuasive copy — never lorem ipsum
- Use professional images: https://loremflickr.com/1920/1080/{business_type},professional,hd,luxury
- Make it feel expensive, custom, unique — nothing template-like
- At least 2200–3500 characters of code
- Variation #{variation_index + 1} — make it visually different from others
"""

    try:
        temperature = 0.88 + (variation_index * 0.06)

        if model:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=9200,
                    top_p=0.94,
                    top_k=48
                )
            )
            html = response.text.strip()
        else:  # OpenAI fallback
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=9000
            )
            html = resp.choices[0].message.content.strip()

        # Clean common AI mistakes
        if "```html" in html:
            html = html.split("```html")[1].split("```")[0].strip()
        if "```" in html:
            html = html.split("```")[1].strip()

        if not html.startswith("<!DOCTYPE"):
            html = "<!DOCTYPE html>\n" + html

        # Force reliable images
        html = re.sub(
            r'https?://source\.unsplash\.com[^\s"\']*',
            f'https://loremflickr.com/1920/1080/{business_type},professional,hd,luxury,high-resolution',
            html
        )

        return html

    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} failed: {str(e)}\n{traceback.format_exc()}"
        print(LAST_AI_ERROR)
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Generation Error</title></head>
        <body style="font-family:sans-serif; text-align:center; padding:100px 20px;">
            <h1 style="color:#e74c3c;">AI Generation Failed</h1>
            <p style="font-size:1.1rem; max-width:600px; margin:30px auto;">
                The AI could not create this design variation.<br>
                Error: <strong>{str(e)}</strong><br><br>
                Please try again or check your API key / quota.
            </p>
        </body>
        </html>
        """

# ROUTES (keeping your original logic)

@app.route('/')
def home():
    return "<h1>AI Website Generator Backend</h1><p>Use the frontend form → /build-with-ai</p>"

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "gemini_model": gemini_model_name if model else "disabled",
        "openai": "active" if client else "disabled",
        "database": "connected" if DATABASE_URL else "missing",
        "last_ai_error": LAST_AI_ERROR[:400] + "..." if len(LAST_AI_ERROR) > 400 else LAST_AI_ERROR
    })

# ... keep all your other routes exactly as they are (/api/generate-site, /api/status/<slug>, /api/select-design, /s/<slug>, /view-design/<slug>/<int:design_index>, /download/<slug>) ...

# Only small improvement in /api/status/<slug> fallback message (optional but helpful)
# In the if not html_content block, you can use the improved fallback from generate_custom_site_html above

if __name__ == '__main__':
    print("AI Website Builder backend starting...")
    app.run(host='0.0.0.0', port=5000, debug=True)
