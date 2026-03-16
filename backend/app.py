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

# ────────────────────────────────────────────────
#  DATABASE
# ────────────────────────────────────────────────

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

# ────────────────────────────────────────────────
#  AI CLIENTS
# ────────────────────────────────────────────────

openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = "models/gemini-2.5-flash"   # <--- most reliable right now

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

# ────────────────────────────────────────────────
#  PATHS (simplified – no Vercel special casing needed anymore)
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TEMP_ROOT = tempfile.gettempdir()
GENERATED_DIR = os.path.join(TEMP_ROOT, "generated-ai-sites")
os.makedirs(GENERATED_DIR, exist_ok=True)

# ────────────────────────────────────────────────
#  AI GENERATION FUNCTION (long version with variation logic)
# ────────────────────────────────────────────────

def generate_custom_site_html(data, variation_index=0):
    global LAST_AI_ERROR
    
    if not model and not client:
        LAST_AI_ERROR = "No AI client available (Gemini or OpenAI key missing)"
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

    # Variation diversity
    layout_patterns = [
        "Hero split-screen + staggered services grid",
        "Full-screen hero with floating cards in wave",
        "Minimal giant typography + bento grid",
        "Diagonal dividers + masonry services",
        "Asymmetric hero right-aligned + horizontal scroll cards",
        "Glassmorphism panels + circular icons",
        "Centered gradient hero + icon tiles"
    ]
    
    selected_layout = layout_patterns[variation_index % len(layout_patterns)]

    prompt = f"""You are a £75,000+ luxury web design lead.

Create ONE completely unique, modern single-file HTML5 landing page for:

Business: {business_name}
Type: {business_type}
Location: {location}
Style preference: {style}
Color palette: Primary {colors[0]}, Secondary {colors[1]}, Accent/BG {colors[2]}

Services: {', '.join(services_list)}

Use this layout style: {selected_layout}

Rules – very strict:
- Return ONLY valid HTML starting with <!DOCTYPE html>
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
        temperature = 0.88 + (variation_index * 0.06)  # slight creativity increase per variation

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

        # Clean markdown/code-block mistakes
        if "```html" in html:
            html = html.split("```html")[1].split("```")[0].strip()
        if not html.startswith("<!DOCTYPE"):
            html = '<!DOCTYPE html>\n' + html

        # Basic image fallback enforcement
        html = re.sub(
            r'https?://source\.unsplash\.com[^\s"\']*',
            f'https://loremflickr.com/1920/1080/{business_type},professional,hd,luxury,high-resolution',
            html
        )

        return html

    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} failed: {str(e)}\n{traceback.format_exc()}"
        print(LAST_AI_ERROR)
        return None

# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

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
        "last_ai_error": LAST_AI_ERROR[:300] + "..." if len(LAST_AI_ERROR) > 300 else LAST_AI_ERROR
    })

@app.route('/api/generate-site', methods=['POST'])
def start_generation():
    try:
        data = request.get_json()
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "businessName is required"}), 400

        name_clean = re.sub(r'[^a-z0-9]+', '-', data['businessName'].lower().strip())
        slug = f"{name_clean}-{random.randint(10000,99999)}"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sites (slug, business_name, business_type, location, services, style, colors, status, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO NOTHING
        """, (
            slug,
            data.get('businessName'),
            data.get('businessType'),
            data.get('location'),
            data.get('services'),
            data.get('style'),
            data.get('colors', []),
            'STARTING',
            'Generation queued...'
        ))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "slug": slug})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/status/<slug>')
def check_status(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()

        if not site:
            conn.close()
            return jsonify({"status": "NOT_FOUND"}), 404

        status = site['status']
        next_variation = -1

        if status == 'STARTING':
            next_variation = 0
        elif status == 'GENERATING_0':
            next_variation = 1
        elif status == 'GENERATING_1':
            next_variation = 2

        base_url = request.host_url.rstrip('/')

        if next_variation >= 0:
            html_content = generate_custom_site_html(dict(site), next_variation)

            if not html_content:
                html_content = "<h1 style='text-align:center; padding:100px;'>AI generation failed – please try again</h1>"

            cur.execute("""
                INSERT INTO variations (site_slug, variation_index, html_content)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (slug, next_variation, html_content))

            new_status = f'GENERATING_{next_variation}' if next_variation < 2 else 'AWAITING_SELECTION'
            cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s",
                       (new_status, f"Design variation {next_variation+1} created", slug))
            conn.commit()

        # Get available variations
        cur.execute("SELECT variation_index FROM variations WHERE site_slug = %s ORDER BY variation_index", (slug,))
        variations = [{"id": row["variation_index"], "url": f"{base_url}/view-design/{slug}/{row['variation_index']}"} 
                      for row in cur.fetchall()]

        response = {
            "status": site['status'],
            "message": site['message'],
            "slug": slug,
            "variations": variations
        }

        if site['status'] in ['AWAITING_SELECTION', 'COMPLETED']:
            response["previewUrl"] = f"{base_url}/s/{slug}"

        conn.close()
        return jsonify(response)

    except psycopg2.Error as db_err:
        return jsonify({"status": "DATABASE_ERROR", "message": str(db_err)}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/api/select-design', methods=['POST'])
def choose_design():
    data = request.get_json()
    slug = data.get('slug')
    design_index = data.get('designIndex')

    if not slug or design_index is None:
        return jsonify({"success": False, "message": "Missing slug or designIndex"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT html_content FROM variations 
            WHERE site_slug = %s AND variation_index = %s
        """, (slug, int(design_index)))
        
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Design not found"}), 404

        final_html = row[0]

        cur.execute("""
            INSERT INTO final_sites (site_slug, html_content)
            VALUES (%s, %s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content = EXCLUDED.html_content
        """, (slug, final_html))

        cur.execute("UPDATE sites SET status = 'COMPLETED', message = 'Website ready to view/download' WHERE slug = %s", (slug,))
        conn.commit()
        conn.close()

        base = request.host_url.rstrip('/')
        return jsonify({
            "success": True,
            "previewUrl": f"{base}/s/{slug}",
            "downloadUrl": f"{base}/download/{slug}"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/s/<slug>')
def show_final_site(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return row[0]
        return "<h1>404 – Website not finalized yet</h1>", 404
    except Exception:
        return "<h1>Server error while loading site</h1>", 500

@app.route('/view-design/<slug>/<int:design_index>')
def preview_variation(slug, design_index):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug = %s AND variation_index = %s",
                    (slug, design_index))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return row[0]
        return "<h1>Design variation not found</h1>", 404
    except Exception:
        return "<h1>Error loading preview</h1>", 500

@app.route('/download/<slug>')
def download_zip(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return "<h1>Not found or not finalized</h1>", 404

        from io import BytesIO
        import zipfile

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0])

        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{slug}_website.zip"
        )
    except Exception as e:
        return f"<h1>Download failed: {str(e)}</h1>", 500

if __name__ == '__main__':
    print("AI Website Builder backend starting...")
    app.run(host='0.0.0.0', port=5000, debug=True)
