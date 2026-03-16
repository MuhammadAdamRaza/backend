import os
import json
import re
import random
import tempfile
import traceback
import zipfile
from io import BytesIO

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv

import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ────────────────────────────────────────────────
#  CATEGORY → IMAGE KEYWORD MAPPING
# ────────────────────────────────────────────────

CATEGORY_IMAGES = {
    "plumber":      ("plumbing,pipes,bathroom,tools",         "💧", "#0ea5e9"),
    "electrician":  ("electrician,wiring,tools,electrical",   "⚡", "#f59e0b"),
    "restaurant":   ("restaurant,food,dining,cuisine",        "🍽️", "#ef4444"),
    "law":          ("law,legal,office,attorney",             "⚖️", "#1e3a5f"),
    "consulting":   ("business,consulting,meeting,office",    "📊", "#6366f1"),
    "fitness":      ("gym,fitness,workout,training",          "💪", "#10b981"),
    "realestate":   ("realestate,house,property,interior",    "🏠", "#f97316"),
    "agency":       ("design,creative,studio,branding",       "🎨", "#8b5cf6"),
    "shoes":        ("shoes,footwear,fashion,sneakers",       "👟", "#ec4899"),
    "beauty":       ("beauty,salon,spa,cosmetics",            "💅", "#f43f5e"),
    "medical":      ("medical,clinic,doctor,health",          "🏥", "#06b6d4"),
    "education":    ("education,school,teaching,learning",    "📚", "#84cc16"),
    "tech":         ("technology,software,computer,coding",   "💻", "#3b82f6"),
    "construction": ("construction,building,architecture",    "🏗️", "#78716c"),
    "cleaning":     ("cleaning,housekeeping,mop,tidy",        "✨", "#14b8a6"),
    "photography":  ("photography,camera,portrait,studio",    "📸", "#a855f7"),
    "other":        ("business,professional,office,success",  "🏢", "#475569"),
}

def get_category_info(business_type):
    bt = (business_type or "other").lower().strip()
    for key in CATEGORY_IMAGES:
        if key in bt:
            return CATEGORY_IMAGES[key]
    return CATEGORY_IMAGES["other"]

# ────────────────────────────────────────────────
#  DATABASE
# ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL:
        print("Warning: DATABASE_URL missing")
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(site_slug, variation_index)
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
        cur.close()
        conn.close()
        print("✅ DB tables ready")
    except Exception as e:
        print(f"DB init error: {e}")

with app.app_context():
    init_db()

# ────────────────────────────────────────────────
#  AI CLIENTS  — tries Gemini first, falls back to OpenAI
# ────────────────────────────────────────────────

# ── Gemini setup ────────────────────────────────
gemini_model = None
GEMINI_KEY   = os.getenv("GEMINI_API_KEY")

# Model names to try in order (most capable → most available)
GEMINI_MODEL_CANDIDATES = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash-latest",
]

if GEMINI_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_KEY)

        # Auto-detect working model
        for candidate in GEMINI_MODEL_CANDIDATES:
            try:
                test_model = genai.GenerativeModel(candidate)
                # Quick probe — very short, cheap call
                test_model.generate_content(
                    "Reply with just: OK",
                    generation_config=genai.types.GenerationConfig(max_output_tokens=5)
                )
                gemini_model      = test_model
                ACTIVE_GEMINI_MODEL = candidate
                print(f"✅ Gemini ready: {candidate}")
                break
            except Exception as probe_err:
                print(f"  ✗ {candidate}: {probe_err}")
                continue

        if not gemini_model:
            print("⚠️  No working Gemini model found — will use OpenAI fallback")
    except ImportError:
        print("google-generativeai not installed")
    except Exception as e:
        print(f"Gemini setup error: {e}")

# ── OpenAI setup ─────────────────────────────────
openai_client = None
OPENAI_KEY    = os.getenv("OPENAI_API_KEY")
if OPENAI_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=OPENAI_KEY)
        print("✅ OpenAI client ready")
    except Exception as e:
        print(f"OpenAI setup error: {e}")

LAST_AI_ERROR = ""

# ────────────────────────────────────────────────
#  HTML GENERATION
# ────────────────────────────────────────────────

LAYOUTS = [
    "Split-screen hero (image left, headline right) + 3-column services grid + dark footer",
    "Full-width hero with centred headline + wave divider + card-based services + testimonial strip",
    "Minimal typographic hero (giant business name) + bento grid services + bold CTA section",
    "Diagonal-cut hero with overlay text + icon services list + stats bar + contact form",
    "Dark hero with gradient text + glassmorphism service cards + light about section",
    "Asymmetric layout with image right + bullet services left + green CTA + newsletter",
    "Retro-bold hero with large serif headline + colour-block service tiles + map section",
]

def build_prompt(data, variation_index):
    name     = data.get('businessName') or data.get('business_name', 'My Business')
    btype    = data.get('businessType') or data.get('business_type', 'business')
    location = data.get('location', 'London')
    services = data.get('services', 'Professional Services')
    style    = data.get('style', 'modern')
    colors   = data.get('colors') or ["#2563eb", "#7c3aed", "#f8fafc"]

    # colors may come from Postgres as a list already
    if isinstance(colors, str):
        colors = json.loads(colors)
    if not colors or len(colors) < 3:
        colors = ["#2563eb", "#7c3aed", "#f8fafc"]

    svc_list     = [s.strip() for s in str(services).split(',') if s.strip()] or ["Premium Services"]
    img_kw, _, _ = get_category_info(btype)
    hero_img     = f"https://loremflickr.com/1920/1080/{img_kw}"
    card_img     = f"https://loremflickr.com/800/500/{img_kw}"
    layout       = LAYOUTS[variation_index % len(LAYOUTS)]

    return f"""You are a senior front-end developer building a premium business website.

OUTPUT RULES — read carefully:
1. Return ONLY raw HTML. Start with <!DOCTYPE html>. No markdown, no backticks, no explanation.
2. All CSS must be inside a single <style> tag in <head>.
3. All JS must be inside a single <script> tag before </body>.
4. Use ONLY Google Fonts and Font Awesome 6 from CDN — no other external resources.
5. Do NOT use Bootstrap, Tailwind, or any CSS framework.
6. The page must be fully responsive (mobile-first).
7. Minimum 4000 characters of total code.

BUSINESS DETAILS:
- Name: {name}
- Industry: {btype}
- Location: {location}
- Style: {style}
- Primary colour: {colors[0]}
- Secondary colour: {colors[1]}
- Background colour: {colors[2]}
- Services: {", ".join(svc_list)}

LAYOUT TO USE (Variation {variation_index + 1} of 3):
{layout}

REQUIRED SECTIONS (in this order):
1. Sticky navigation bar with business name logo and smooth-scroll links
2. Hero section with headline, subheadline, and CTA button — use this image: {hero_img}
3. About Us section — write 2 paragraphs about {name} in {location}
4. Services section — show EVERY service from the list above as a card with icon and description — use: {card_img}
5. Why Choose Us — 4 feature tiles with icons
6. Testimonials — 3 fake customer quotes
7. Contact / CTA section with phone, email fields and a submit button
8. Footer with copyright

COPY RULES:
- Write REAL, persuasive marketing copy specific to {btype} businesses in {location}
- Never write lorem ipsum
- Headlines should be compelling and benefit-driven

Now output the complete single-file HTML page for Variation {variation_index + 1}:"""


def generate_html(data, variation_index):
    global LAST_AI_ERROR

    if not gemini_model and not openai_client:
        LAST_AI_ERROR = "No AI client configured. Add GEMINI_API_KEY or OPENAI_API_KEY to env vars."
        print(f"❌ {LAST_AI_ERROR}")
        return None

    prompt      = build_prompt(data, variation_index)
    temperature = round(0.7 + variation_index * 0.08, 2)

    try:
        # ── Try Gemini ───────────────────────────────────────
        if gemini_model:
            print(f"  🤖 Gemini generating variation {variation_index}…")
            response = gemini_model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=8192,
                    top_p=0.95,
                )
            )
            raw = response.text.strip()

        # ── Fallback to OpenAI ────────────────────────────────
        elif openai_client:
            print(f"  🤖 OpenAI generating variation {variation_index}…")
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=8000,
            )
            raw = resp.choices[0].message.content.strip()

        # ── Clean up model output ─────────────────────────────
        # Strip markdown code fences if model added them
        if "```html" in raw:
            raw = raw.split("```html", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

        if not raw.lower().startswith("<!doctype"):
            raw = "<!DOCTYPE html>\n" + raw

        # Replace any unsplash/picsum placeholders with category images
        img_kw, _, _ = get_category_info(
            data.get('businessType') or data.get('business_type', 'business')
        )
        raw = re.sub(
            r'https?://(?:source\.unsplash\.com|picsum\.photos|via\.placeholder\.com)[^\s"\']*',
            f'https://loremflickr.com/1920/1080/{img_kw}',
            raw
        )

        print(f"  ✅ Variation {variation_index} generated ({len(raw)} chars)")
        LAST_AI_ERROR = ""
        return raw

    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} error: {type(e).__name__}: {e}"
        print(f"  ❌ {LAST_AI_ERROR}")
        traceback.print_exc()
        return None


# ────────────────────────────────────────────────
#  CONVERSION BANNER (injected into final site)
# ────────────────────────────────────────────────

def inject_conversion_banner(html, site, slug, base_url):
    name     = site.get('business_name', 'Your Business')
    btype    = site.get('business_type', 'business')
    _, emoji, accent = get_category_info(btype)
    dl_url   = f"{base_url}/download/{slug}"
    wa_url   = "https://wa.me/447700000000?text=I'd+like+to+launch+my+AI+website"

    banner = f"""
<style>
#_cta{{position:fixed;bottom:0;left:0;right:0;z-index:999999;
  background:linear-gradient(135deg,#0f172a,#1e293b);
  color:#fff;padding:14px 24px;display:flex;align-items:center;
  justify-content:space-between;gap:12px;flex-wrap:wrap;
  box-shadow:0 -6px 32px rgba(0,0,0,.35);
  font-family:'Segoe UI',system-ui,sans-serif}}
#_cta .l{{display:flex;align-items:center;gap:10px}}
#_cta .badge{{background:{accent};color:#fff;padding:3px 10px;border-radius:20px;
  font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase}}
#_cta .txt{{font-size:14px;line-height:1.4}}
#_cta .txt strong{{font-size:15px}}
#_cta .r{{display:flex;gap:8px;flex-wrap:wrap}}
#_cta a,#_cta button{{padding:10px 18px;border-radius:30px;font-weight:700;
  font-size:13px;cursor:pointer;border:none;text-decoration:none;
  display:inline-flex;align-items:center;gap:5px;transition:.2s}}
#_cta .g{{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}}
#_cta .d{{background:rgba(255,255,255,.1);color:#fff;
  border:1px solid rgba(255,255,255,.2)!important}}
#_cta .x{{background:transparent;color:rgba(255,255,255,.4);
  font-size:18px;padding:4px 8px}}
body{{padding-bottom:80px!important}}
</style>
<div id="_cta">
  <div class="l">
    <span class="badge">✨ AI Preview</span>
    <div class="txt">
      <strong>{emoji} {name} — Your website is ready!</strong><br>
      Our team will finalise &amp; launch it for you — <strong style="color:#4ade80">completely free</strong>
    </div>
  </div>
  <div class="r">
    <a href="{wa_url}" target="_blank" class="g">🚀 Launch My Site Free</a>
    <a href="{dl_url}" class="d">⬇ Download HTML</a>
    <button class="x" onclick="document.getElementById('_cta').remove();document.body.style.paddingBottom=0">✕</button>
  </div>
</div>"""

    return html.replace("</body>", f"{banner}\n</body>") if "</body>" in html else html + banner


# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

@app.route('/')
def home():
    return "<h1>AI Website Builder — Backend OK</h1>"


@app.route('/health')
def health():
    return jsonify({
        "status":       "ok",
        "gemini":       ACTIVE_GEMINI_MODEL if gemini_model else "disabled",
        "openai":       "active" if openai_client else "disabled",
        "database":     "connected" if DATABASE_URL else "missing",
        "last_error":   LAST_AI_ERROR or "none",
    })


@app.route('/api/debug')
def debug():
    """Quick diagnostic — call this if something goes wrong."""
    info = {
        "gemini_key_set":   bool(GEMINI_KEY),
        "openai_key_set":   bool(OPENAI_KEY),
        "gemini_model":     ACTIVE_GEMINI_MODEL if gemini_model else None,
        "openai_active":    bool(openai_client),
        "database_url_set": bool(DATABASE_URL),
        "last_ai_error":    LAST_AI_ERROR or "none",
    }
    return jsonify(info)


# ── Step 1: Register job ─────────────────────────
@app.route('/api/generate-site', methods=['POST'])
def start_generation():
    try:
        data = request.get_json()
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "businessName is required"}), 400

        slug = re.sub(r'[^a-z0-9]+', '-', data['businessName'].lower().strip())
        slug = f"{slug}-{random.randint(10000, 99999)}"

        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sites
              (slug, business_name, business_type, location, services, style, colors, status, message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'STARTING','Job registered')
            ON CONFLICT (slug) DO NOTHING
        """, (
            slug,
            data.get('businessName'),
            data.get('businessType', 'other'),
            data.get('location', ''),
            data.get('services', ''),
            data.get('style', 'modern'),
            data.get('colors', []),
        ))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "slug": slug})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Step 2: Poll + trigger AI generation ────────
@app.route('/api/status/<slug>')
def check_status(slug):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()

        if not site:
            conn.close()
            return jsonify({"status": "NOT_FOUND"}), 404

        current_status = site['status']

        # Map status → which variation to generate next
        STATUS_TO_NEXT = {
            'STARTING':     0,
            'GENERATING_0': 1,
            'GENERATING_1': 2,
        }

        next_var = STATUS_TO_NEXT.get(current_status, -1)

        if next_var >= 0:
            print(f"[{slug}] Generating variation {next_var}…")
            html = generate_html(dict(site), next_var)

            if not html:
                # Mark as FAILED so the frontend can show a real error
                err_msg = LAST_AI_ERROR or "AI generation returned empty response"
                cur.execute(
                    "UPDATE sites SET status='FAILED', message=%s WHERE slug=%s",
                    (err_msg, slug)
                )
                conn.commit()
                conn.close()
                return jsonify({"status": "FAILED", "message": err_msg})

            # Save variation
            cur.execute("""
                INSERT INTO variations (site_slug, variation_index, html_content)
                VALUES (%s, %s, %s)
                ON CONFLICT (site_slug, variation_index) DO UPDATE
                  SET html_content = EXCLUDED.html_content
            """, (slug, next_var, html))

            # Advance status
            new_status = f'GENERATING_{next_var}' if next_var < 2 else 'AWAITING_SELECTION'
            new_msg    = (f"Design {next_var + 1} of 3 created…"
                          if next_var < 2 else "All 3 designs ready!")
            cur.execute(
                "UPDATE sites SET status=%s, message=%s WHERE slug=%s",
                (new_status, new_msg, slug)
            )
            conn.commit()
            current_status = new_status   # ← use the UPDATED status in the response

        # Fetch available variation URLs
        base = request.host_url.rstrip('/')
        cur.execute(
            "SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",
            (slug,)
        )
        variations = [
            {"id": r["variation_index"],
             "url": f"{base}/view-design/{slug}/{r['variation_index']}"}
            for r in cur.fetchall()
        ]

        resp = {
            "status":     current_status,
            "message":    site['message'],
            "slug":       slug,
            "variations": variations,
        }
        if current_status in ('AWAITING_SELECTION', 'COMPLETED'):
            resp["selectionUrl"] = f"{base}/select/{slug}"
            resp["previewUrl"]   = f"{base}/s/{slug}"

        conn.close()
        return jsonify(resp)

    except psycopg2.Error as db_err:
        return jsonify({"status": "DATABASE_ERROR", "message": str(db_err)}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# ── Step 3: Select a design ──────────────────────
@app.route('/api/select-design', methods=['POST'])
def select_design():
    data = request.get_json() or {}
    slug  = data.get('slug')
    index = data.get('designIndex')

    if not slug or index is None:
        return jsonify({"success": False, "message": "slug and designIndex required"}), 400

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s",
            (slug, int(index))
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Design not found"}), 404

        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()

        base      = request.host_url.rstrip('/')
        final_html = inject_conversion_banner(row['html_content'], dict(site), slug, base)

        cur.execute("""
            INSERT INTO final_sites (site_slug, html_content)
            VALUES (%s, %s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content = EXCLUDED.html_content
        """, (slug, final_html))

        cur.execute(
            "UPDATE sites SET status='COMPLETED', message='Website ready' WHERE slug=%s",
            (slug,)
        )
        conn.commit()
        conn.close()

        return jsonify({
            "success":     True,
            "previewUrl":  f"{base}/s/{slug}",
            "downloadUrl": f"{base}/download/{slug}",
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Serve the chosen final site ──────────────────
@app.route('/s/<slug>')
def show_site(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        return (row[0], 200, {'Content-Type': 'text/html'}) if row else ("<h1>404</h1>", 404)
    except Exception:
        return "<h1>Server error</h1>", 500


# ── Preview a single variation ───────────────────
@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s",
            (slug, idx)
        )
        row = cur.fetchone()
        conn.close()
        return (row[0], 200, {'Content-Type': 'text/html'}) if row else ("<h1>Not found</h1>", 404)
    except Exception:
        return "<h1>Error</h1>", 500


# ── Download site as ZIP ─────────────────────────
@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return "<h1>Not found</h1>", 404

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0])
        buf.seek(0)
        return send_file(buf, mimetype='application/zip',
                         as_attachment=True, download_name=f"{slug}_website.zip")
    except Exception as e:
        return f"<h1>Error: {e}</h1>", 500


# ── Select / inline design-picker page ───────────
@app.route('/select/<slug>')
def select_page(slug):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()
        cur.execute(
            "SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",
            (slug,)
        )
        variations = cur.fetchall()
        conn.close()

        if not site:
            return "<h1>Not found</h1>", 404

        name   = site['business_name'] or 'Your Business'
        btype  = site['business_type']  or 'business'
        _, emoji, accent = get_category_info(btype)
        base   = request.host_url.rstrip('/')

        cards = ""
        for v in variations:
            i = v['variation_index']
            cards += f"""
            <div class="card">
              <div class="label">
                <span class="badge">Design {i+1}</span>
                <span class="sub">AI Generated Layout</span>
              </div>
              <div class="preview-wrap">
                <iframe src="{base}/view-design/{slug}/{i}" loading="lazy"></iframe>
                <div class="overlay" onclick="pick('{slug}',{i})"></div>
              </div>
              <div class="foot">
                <button class="pick-btn" onclick="pick('{slug}',{i})">✅ Choose This Design</button>
                <a href="{base}/view-design/{slug}/{i}" target="_blank" class="prev-btn">👁 Full Preview</a>
              </div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Choose Your Design — {name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;background:#f0f4ff;color:#0f172a}}
header{{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.95);
  backdrop-filter:blur(12px);border-bottom:1px solid rgba(0,0,0,.07);
  padding:16px 32px;display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:1rem;font-weight:700}}
.back{{color:#64748b;font-size:13px;font-weight:600;padding:8px 16px;
  border-radius:20px;border:1px solid #e2e8f0;text-decoration:none}}
.hero{{text-align:center;padding:60px 24px 48px;
  background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);color:#fff}}
.tag{{display:inline-block;background:{accent};color:#fff;padding:6px 18px;
  border-radius:30px;font-size:11px;font-weight:700;letter-spacing:1px;
  text-transform:uppercase;margin-bottom:20px}}
.hero h2{{font-size:clamp(1.8rem,4vw,3rem);font-weight:900;letter-spacing:-.02em;margin-bottom:10px}}
.hero p{{color:rgba(255,255,255,.65);font-size:1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
  gap:24px;max-width:1280px;margin:40px auto 60px;padding:0 24px}}
.card{{background:#fff;border-radius:20px;overflow:hidden;
  box-shadow:0 10px 40px rgba(0,0,0,.08);transition:.3s}}
.card:hover{{transform:translateY(-6px);box-shadow:0 24px 60px rgba(0,0,0,.13)}}
.label{{padding:16px 20px 12px;display:flex;align-items:center;gap:10px}}
.badge{{background:{accent};color:#fff;font-size:10px;font-weight:700;
  padding:3px 10px;border-radius:20px;text-transform:uppercase;letter-spacing:.5px}}
.sub{{color:#94a3b8;font-size:12px}}
.preview-wrap{{position:relative;height:440px;overflow:hidden}}
.preview-wrap iframe{{width:100%;height:100%;border:none;pointer-events:none;
  transform:scale(.95);transform-origin:top center}}
.overlay{{position:absolute;inset:0;cursor:pointer}}
.overlay:hover{{background:rgba(79,70,229,.04)}}
.foot{{padding:16px 20px;display:flex;gap:8px}}
.pick-btn{{flex:1;background:linear-gradient(135deg,{accent},#818cf8);color:#fff;
  border:none;padding:12px;border-radius:12px;font-size:13px;font-weight:700;cursor:pointer}}
.pick-btn:hover{{opacity:.9;transform:translateY(-1px)}}
.prev-btn{{background:#f1f5f9;color:#475569;padding:12px 16px;border-radius:12px;
  text-decoration:none;font-size:12px;font-weight:600}}
#loader{{display:none;position:fixed;inset:0;background:rgba(15,23,42,.85);
  backdrop-filter:blur(8px);z-index:9999;flex-direction:column;
  align-items:center;justify-content:center;color:#fff}}
.ring{{width:60px;height:60px;border:4px solid rgba(255,255,255,.15);
  border-top-color:{accent};border-radius:50%;animation:spin .8s linear infinite;margin-bottom:20px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
#loader h3{{font-size:1.4rem;font-weight:700}}
</style></head><body>
<header><h1>{emoji} {name}</h1><a href="{base}/build-with-ai" class="back">← Start Over</a></header>
<div class="hero">
  <div class="tag">✨ AI Generation Complete</div>
  <h2>Choose Your Favourite Design</h2>
  <p>Three unique AI-crafted layouts built for {name}. Pick the one you love.</p>
</div>
<div class="grid">{cards}</div>
<div id="loader"><div class="ring"></div><h3>Finalising your website…</h3></div>
<script>
async function pick(slug,index){{
  document.getElementById('loader').style.display='flex';
  try{{
    const r=await fetch('{base}/api/select-design',{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{slug,designIndex:index}})
    }});
    const d=await r.json();
    if(d.success){{window.location=d.previewUrl}}
    else{{alert('Error: '+(d.message||'Unknown'));document.getElementById('loader').style.display='none'}}
  }}catch(e){{alert('Error: '+e.message);document.getElementById('loader').style.display='none'}}
}}
</script></body></html>"""
    except Exception as e:
        traceback.print_exc()
        return f"<h1>Error: {e}</h1>", 500


if __name__ == '__main__':
    print("🚀 AI Website Builder starting…")
    app.run(host='0.0.0.0', port=5000, debug=True)
