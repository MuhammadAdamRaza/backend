import os
import json
import sys
import tempfile
import re
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
CORS(app, resources={r"/*": {"origins": "*"}})  # Very permissive for development

# ────────────────────────────────────────────────
#                DATABASE CONFIG
# ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set in environment variables.")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL:
        print("⚠️  DATABASE_URL missing → skipping DB initialization")
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
        print("✅ Database tables initialized")
    except Exception as e:
        print(f"DB init warning (non-fatal): {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

# Run init once at startup (soft fail allowed)
with app.app_context():
    init_db()

# ────────────────────────────────────────────────
#                   AI CLIENTS
# ────────────────────────────────────────────────

openai_key = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = "models/gemini-1.5-flash"   # ← Default & most reliable 2025–2026

gemini_model = None
if gemini_key:
    try:
        genai.configure(api_key=gemini_key)
        gemini_model = genai.GenerativeModel(gemini_model_name)
        print(f"Gemini ready → using model: {gemini_model_name}")
    except Exception as e:
        print(f"Gemini initialization failed: {e}")
else:
    print("No GEMINI_API_KEY → Gemini disabled")

# ────────────────────────────────────────────────
#                DIRECTORY & PATHS
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TEMP_DIR = tempfile.gettempdir()
GENERATED_DIR = os.path.join(TEMP_DIR, 'ai-generated-sites')
os.makedirs(GENERATED_DIR, exist_ok=True)

# ────────────────────────────────────────────────
#                   HELPERS
# ────────────────────────────────────────────────

def ensure_file(rel_path):
    """Only used for local development fallback — not critical on Vercel"""
    local_path = os.path.join(PROJECT_ROOT, rel_path)
    if os.path.exists(local_path):
        return local_path
    return None

# ────────────────────────────────────────────────
#              AI GENERATION CORE
# ────────────────────────────────────────────────

def generate_custom_site_html(data, variation_index=0):
    if not gemini_model and not openai_client:
        return None

    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'business')
    location = data.get('location', 'International')
    style = data.get('style', 'modern')
    services = data.get('services', 'Services')
    colors = data.get('colors', ['#2563eb', '#7c3aed', '#f8fafc'])

    services_list = [s.strip() for s in services.split(',') if s.strip()][:5]
    if not services_list:
        services_list = ['Professional Service', 'Expert Solutions']

    # ── Design variation logic ──────────────────────────────────────
    layouts = [
        "Hero split with overlapping image + staggered grid services",
        "Full-screen immersive hero + floating circular service cards",
        "Minimal giant headline + bento-box layout",
        "Diagonal cuts + masonry portfolio-style services",
        "Asymmetric layout + horizontal scroll cards"
    ]
    selected_layout = layouts[variation_index % len(layouts)]

    prompt = f"""You are an elite luxury web designer (think £80,000+ projects).
Create a **completely unique single-file HTML5 landing page** for:

Business: {business_name}
Type: {business_type}
Location: {location}
Style: {style}
Colors: Primary {colors[0]}, Secondary {colors[1]}, Accent/BG {colors[2]}

Services to highlight: {', '.join(services_list)}

Use layout pattern: {selected_layout}

Rules:
- Return ONLY raw HTML starting with <!DOCTYPE html>
- Embed all CSS in <style> and JS in <script>
- Use Google Fonts + Font Awesome CDN only
- Pure CSS (no Tailwind, no Bootstrap)
- Responsive (mobile-first)
- Real compelling copy — no lorem ipsum
- Use placeholder images: https://loremflickr.com/1920/1080/{business_type},professional,hd
- Minimum 2200 characters of code
- Make it look expensive, modern, custom — NOT like any template
"""

    try:
        if gemini_model:
            response = gemini_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.9,
                    max_output_tokens=8500
                )
            )
            html = response.text.strip()
        elif openai_client:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8500,
                temperature=0.85
            )
            html = resp.choices[0].message.content.strip()
        else:
            return None

        # Clean up common AI markdown mistakes
        if html.startswith("```html"):
            html = html.split("```html")[1].split("```")[0].strip()
        if not html.startswith("<!DOCTYPE"):
            html = "<!DOCTYPE html>\n" + html

        return html
    except Exception as e:
        print(f"AI generation failed (variation {variation_index}): {e}")
        return None

# ────────────────────────────────────────────────
#                   ROUTES
# ────────────────────────────────────────────────

@app.route('/')
def home():
    return "<h1>AI Website Builder Backend</h1><p>Use /build-with-ai or API endpoints.</p>"

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "gemini_active": bool(gemini_model),
        "openai_active": bool(openai_client),
        "db_connected": bool(DATABASE_URL)
    })

@app.route('/api/generate-site', methods=['POST', 'OPTIONS'])
def generate_site():
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 204

    try:
        data = request.json
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "Missing businessName"}), 400

        slug_base = data['businessName'].lower().replace(' ', '-').replace("'", "").strip()
        slug = f"{slug_base}-{random.randint(10000, 99999)}"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sites (slug, business_name, business_type, location, services, style, colors, status, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            slug,
            data.get('businessName'),
            data.get('businessType'),
            data.get('location'),
            data.get('services'),
            data.get('style'),
            data.get('colors'),
            'STARTING',
            'Preparing generation...'
        ))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "slug": slug})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/status/<slug>')
def get_status(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()

        if not site:
            conn.close()
            return jsonify({"status": "NOT_FOUND", "message": "Site not found"}), 404

        current_status = site['status']
        target_variation = -1
        next_status = ""

        if current_status == 'STARTING':
            target_variation = 0
            next_status = 'GENERATING_0'
        elif current_status == 'GENERATING_0':
            target_variation = 1
            next_status = 'GENERATING_1'
        elif current_status == 'GENERATING_1':
            target_variation = 2
            next_status = 'READY_FOR_CHOICE'

        base_url = request.host_url.rstrip('/')

        if target_variation >= 0:
            html = generate_custom_site_html({
                "businessName": site['business_name'],
                "businessType": site['business_type'],
                "location": site['location'],
                "services": site['services'],
                "style": site['style'],
                "colors": site['colors']
            }, variation_index=target_variation)

            if not html:
                html = "<h1>Generation failed — please try again</h1>"

            cur.execute("""
                INSERT INTO variations (site_slug, variation_index, html_content)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (slug, target_variation, html))

            cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s",
                        (next_status, f"Design {target_variation+1} ready", slug))
            conn.commit()

        # Fetch variations if available
        cur.execute("SELECT variation_index FROM variations WHERE site_slug = %s ORDER BY variation_index", (slug,))
        vars_list = cur.fetchall()

        response = {
            "status": site['status'],
            "message": site['message'],
            "slug": slug,
            "variations": [
                {"id": v['variation_index'], "url": f"{base_url}/view-design/{slug}/{v['variation_index']}"}
                for v in vars_list
            ]
        }

        if site['status'] in ['READY_FOR_CHOICE', 'COMPLETED']:
            response["previewUrl"] = f"{base_url}/s/{slug}"

        conn.close()
        return jsonify(response)

    except psycopg2.Error as db_err:
        return jsonify({"status": "DB_ERROR", "message": str(db_err)}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/api/select-design', methods=['POST'])
def select_design():
    try:
        data = request.json
        slug = data.get('slug')
        idx = data.get('designIndex')

        if not slug or idx is None:
            return jsonify({"success": False, "message": "Missing slug or designIndex"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT html_content FROM variations
            WHERE site_slug = %s AND variation_index = %s
        """, (slug, int(idx)))
        row = cur.fetchone()

        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Selected design not found"}), 404

        chosen_html = row[0]

        # Optional: wrap with simple preview bar (or keep clean)
        final_html = chosen_html

        cur.execute("""
            INSERT INTO final_sites (site_slug, html_content)
            VALUES (%s, %s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content = EXCLUDED.html_content
        """, (slug, final_html))

        cur.execute("UPDATE sites SET status = 'COMPLETED', message = 'Website ready!' WHERE slug = %s", (slug,))
        conn.commit()
        conn.close()

        base_url = request.host_url.rstrip('/')
        return jsonify({
            "success": True,
            "previewUrl": f"{base_url}/s/{slug}",
            "downloadUrl": f"{base_url}/download/{slug}"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/s/<slug>')
def serve_final_site(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return "<h1>Site not found or not finalized</h1>", 404

        return row[0]
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>", 500

@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug = %s AND variation_index = %s", (slug, idx))
        row = cur.fetchone()
        conn.close()

        if not row:
            return "<h1>Variation not found</h1>", 404

        return row[0]
    except Exception as e:
        return f"<h1>Error: {str(e)}</h1>", 500

@app.route('/download/<slug>')
def download_site(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return "<h1>Site not found</h1>", 404

        from io import BytesIO
        import zipfile

        mem = BytesIO()
        with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0].encode('utf-8'))

        mem.seek(0)
        return send_file(
            mem,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{slug}-website.zip"
        )
    except Exception as e:
        return f"<h1>Download error: {str(e)}</h1>", 500

if __name__ == '__main__':
    print("Starting AI Website Builder (debug mode)")
    app.run(host='0.0.0.0', port=5000, debug=True)
