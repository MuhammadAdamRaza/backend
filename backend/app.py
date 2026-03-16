import os
import re
import random
import traceback
import tempfile
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from io import BytesIO
import zipfile

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ────────────────────────────────────────────────
# DATABASE CONFIG
# ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set")
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
        print("Database tables ready")
    except Exception as e:
        print(f"DB init warning: {e}")
    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()

with app.app_context():
    init_db()

# ────────────────────────────────────────────────
# GEMINI ONLY – multiple stable model attempts
# ────────────────────────────────────────────────

gemini_key = os.getenv("GEMINI_API_KEY")
model = None

if gemini_key:
    try:
        genai.configure(api_key=gemini_key)

        # Try stable models in order of reliability (March 2026)
        for model_name in [
            "gemini-1.5-flash",          # most stable & fast
            "gemini-1.5-flash-8b",       # smaller & faster variant
            "gemini-1.5-pro",            # better quality
            "gemini-2.0-flash-exp"       # experimental newer flash
        ]:
            try:
                model = genai.GenerativeModel(model_name)
                print(f"Gemini model loaded successfully: {model_name}")
                break
            except Exception as inner_e:
                print(f"Model {model_name} failed to load: {inner_e}")
                continue

        if model is None:
            print("No usable Gemini model could be loaded")
    except Exception as e:
        print(f"Gemini configuration failed: {e}")
        model = None

# ────────────────────────────────────────────────
# BEAUTIFUL FALLBACK HTML – never blank page
# ────────────────────────────────────────────────

FALLBACK_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{business_name} - Coming Soon</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin:0; padding:0; background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); min-height:100vh; display:flex; align-items:center; justify-content:center; }}
    .card {{ background:white; border-radius:16px; box-shadow:0 10px 40px rgba(0,0,0,0.12); padding:40px; max-width:720px; text-align:center; }}
    h1 {{ color:#1d4ed8; font-size:3rem; margin-bottom:0.5rem; }}
    .subtitle {{ font-size:1.4rem; color:#555; margin-bottom:2rem; }}
    .services {{ display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin:2rem 0; }}
    .service {{ background:#eff6ff; color:#1d4ed8; padding:10px 20px; border-radius:50px; font-weight:500; }}
    .cta {{ display:inline-block; background:#1d4ed8; color:white; padding:16px 40px; border-radius:50px; text-decoration:none; font-weight:600; margin-top:2rem; font-size:1.2rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{business_name}</h1>
    <div class="subtitle">{business_type} • {location}</div>
    <p style="font-size:1.15rem; color:#444; max-width:600px; margin:0 auto 2rem;">
      We're building your custom website right now.<br>
      <strong>Our team will finalize and launch it for you shortly – completely free of charge.</strong>
    </p>
    <div class="services">
      {services_html}
    </div>
    <a href="mailto:support@yourdomain.com" class="cta">Contact Us to Speed Up Launch</a>
  </div>
</body>
</html>
"""

# ────────────────────────────────────────────────
# AI GENERATION – Gemini only, multiple attempts
# ────────────────────────────────────────────────

def generate_custom_site_html(data, variation_index=0):
    if not model:
        print("No Gemini model available")
        return create_fallback_html(data)

    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'Professional Services')
    location     = data.get('location', 'Lahore')
    services     = data.get('services', '')
    style        = data.get('style', 'modern')
    colors       = data.get('colors', ["#2563eb", "#7c3aed", "#f8fafc"])

    services_list = [s.strip() for s in services.split(',') if s.strip()][:6]
    if not services_list:
        services_list = ["Professional Service", "Expert Solutions", "Quality Results"]

    prompt = f"""Create a modern, responsive single-page HTML5 website for:

Business: {business_name}
Category: {business_type}
Location: {location}
Style: {style}
Colors: primary {colors[0]}, secondary {colors[1]}, background/accent {colors[2]}

Services: {', '.join(services_list)}

Rules:
- Return ONLY complete HTML code starting with <!DOCTYPE html>
- No explanations, no markdown, no ``` fences
- All styles in <style> tag, scripts in <script>
- Use Google Fonts + Font Awesome CDN only
- Mobile-first responsive design
- Real business-oriented copy, no lorem ipsum
- Images from: https://loremflickr.com/1920/1080/{business_type},professional,hd,luxury
- Make it look premium and custom
- Variation {variation_index + 1} – use different layout approach
"""

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.82,
                max_output_tokens=9500,
                top_p=0.94,
                top_k=40
            )
        )
        html = response.text.strip()

        # Clean up
        if html.startswith("```html"):
            html = html.split("```html", 1)[1].rsplit("```", 1)[0].strip()
        if not html.startswith("<!DOCTYPE"):
            html = "<!DOCTYPE html>\n" + html

        # Fix broken image URLs
        html = re.sub(r'(source\.unsplash\.com|images\.unsplash\.com)[^\s"\']*',
                      f'https://loremflickr.com/1920/1080/{business_type},professional,hd,luxury',
                      html)

        print(f"Generated variation {variation_index} ({len(html)} chars)")
        return html

    except Exception as e:
        error_msg = f"Gemini error (var {variation_index}): {str(e)}"
        print(error_msg)
        traceback.print_exc()
        return create_fallback_html(data)

def create_fallback_html(data):
    business_name = data.get('businessName', 'Your Business')
    business_type = data.get('businessType', 'Professional Services')
    location = data.get('location', 'Your City')
    services = data.get('services', 'Services')

    services_html = ''.join(
        f'<div class="service">{s.strip()}</div>'
        for s in services.split(',') if s.strip()
    ) or '<div class="service">Quality Services</div>'

    return FALLBACK_HTML_TEMPLATE.format(
        business_name=business_name,
        business_type=business_type,
        location=location,
        services_html=services_html
    )

# ────────────────────────────────────────────────
# ALL ROUTES – FULLY RESTORED
# ────────────────────────────────────────────────

@app.route('/')
def home():
    return "<h1>AI Website Generator Backend</h1><p>Use the frontend form → /build-with-ai</p>"

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "gemini_active": bool(model),
        "model_name": model.model_name if model else "none",
        "database": "connected" if DATABASE_URL else "missing"
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

            cur.execute("""
                INSERT INTO variations (site_slug, variation_index, html_content)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (slug, next_variation, html_content))

            new_status = f'GENERATING_{next_variation}' if next_variation < 2 else 'AWAITING_SELECTION'
            cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s",
                       (new_status, f"Design variation {next_variation+1} created", slug))
            conn.commit()

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
    print("AI Website Builder backend starting (Gemini only mode)...")
    app.run(host='0.0.0.0', port=5000, debug=True)
