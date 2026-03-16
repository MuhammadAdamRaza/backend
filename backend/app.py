import os
import json
import re
import random
import traceback
import zipfile
from io import BytesIO

from flask import Flask, request, jsonify, send_file, Response
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
    "plumber":      ("plumbing,pipes,bathroom,tools",        "💧", "#0ea5e9"),
    "electrician":  ("electrician,wiring,tools,electrical",  "⚡", "#f59e0b"),
    "restaurant":   ("restaurant,food,dining,cuisine",       "🍽️", "#ef4444"),
    "law":          ("law,legal,office,attorney",            "⚖️", "#1e3a5f"),
    "consulting":   ("business,consulting,meeting,office",   "📊", "#6366f1"),
    "fitness":      ("gym,fitness,workout,training",         "💪", "#10b981"),
    "realestate":   ("realestate,house,property,interior",   "🏠", "#f97316"),
    "agency":       ("design,creative,studio,branding",      "🎨", "#8b5cf6"),
    "shoes":        ("shoes,footwear,fashion,sneakers",      "👟", "#ec4899"),
    "beauty":       ("beauty,salon,spa,cosmetics",           "💅", "#f43f5e"),
    "medical":      ("medical,clinic,doctor,health",         "🏥", "#06b6d4"),
    "education":    ("education,school,teaching,learning",   "📚", "#84cc16"),
    "tech":         ("technology,software,computer,coding",  "💻", "#3b82f6"),
    "construction": ("construction,building,architecture",   "🏗️", "#78716c"),
    "cleaning":     ("cleaning,housekeeping,mop,tidy",       "✨", "#14b8a6"),
    "photography":  ("photography,camera,portrait,studio",   "📸", "#a855f7"),
    "other":        ("business,professional,office,success", "🏢", "#475569"),
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
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL missing — DB disabled")
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                slug          TEXT PRIMARY KEY,
                business_name TEXT,
                business_type TEXT,
                location      TEXT,
                services      TEXT,
                style         TEXT,
                colors        TEXT[],
                status        TEXT,
                message       TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS variations (
                id              SERIAL PRIMARY KEY,
                site_slug       TEXT REFERENCES sites(slug) ON DELETE CASCADE,
                variation_index INT,
                html_content    TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Add UNIQUE constraint if it doesn't already exist (safe to run repeatedly)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'variations_site_slug_variation_index_key'
                ) THEN
                    ALTER TABLE variations
                    ADD CONSTRAINT variations_site_slug_variation_index_key
                    UNIQUE (site_slug, variation_index);
                END IF;
            END$$;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS final_sites (
                site_slug    TEXT PRIMARY KEY REFERENCES sites(slug) ON DELETE CASCADE,
                html_content TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("DB tables ready")
    except Exception as e:
        print(f"DB init error: {e}")

with app.app_context():
    init_db()

# ────────────────────────────────────────────────
#  AI CLIENT  — NEW google-genai SDK
#  Install:  pip install google-genai
# ────────────────────────────────────────────────

# Try multiple common env var names for Gemini key
GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY") or
    os.getenv("GOOGLE_API_KEY") or
    os.getenv("GOOGLE_GEMINI_KEY") or
    os.getenv("GCP_API_KEY") or
    ""
)

# Try multiple common env var names for OpenAI key
OPENAI_KEY = (
    os.getenv("OPENAI_API_KEY") or
    os.getenv("OPENAI_KEY") or
    ""
)

print(f"ENV CHECK — GEMINI_KEY set: {bool(GEMINI_KEY)} | OPENAI_KEY set: {bool(OPENAI_KEY)}")
print(f"ALL ENV VARS: {[k for k in os.environ.keys()]}")

gemini_client = None
openai_client = None
ACTIVE_MODEL  = None
LAST_AI_ERROR = ""

# ── New google-genai SDK ──────────────────────────
# Model probe happens at first call, not at startup,
# so a cold Vercel boot doesn't burn time/quota.
# Exact model IDs confirmed available on this account (from /api/list-models)
GEMINI_CANDIDATES = [
    "gemini-2.5-flash",        # best quality - confirmed available
    "gemini-2.0-flash",        # fast + reliable - confirmed available
    "gemini-2.0-flash-001",    # stable version - confirmed available
    "gemini-2.0-flash-lite",   # lightweight fallback - confirmed available
    "gemini-flash-latest",     # alias - confirmed available
    "gemini-pro-latest",       # pro alias - confirmed available
]

if GEMINI_KEY:
    try:
        from google import genai as google_genai
        gemini_client = google_genai.Client(api_key=GEMINI_KEY)
        # Don't probe at startup — set default model and confirm at first use
        ACTIVE_MODEL  = "gemini-2.5-flash"
        print(f"Gemini client ready (default model: {ACTIVE_MODEL})")
    except ImportError:
        print("ERROR: google-genai not installed — add 'google-genai' to requirements.txt")
    except Exception as e:
        print(f"Gemini client error: {e}")
        gemini_client = None
else:
    print("WARNING: No Gemini key found in environment variables")

# ── OpenAI fallback ───────────────────────────────
if OPENAI_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=OPENAI_KEY)
        if not ACTIVE_MODEL:
            ACTIVE_MODEL = "gpt-4o-mini"
        print(f"OpenAI client ready")
    except ImportError:
        print("ERROR: openai not installed — add 'openai' to requirements.txt")
    except Exception as e:
        print(f"OpenAI client error: {e}")

# ────────────────────────────────────────────────
#  PROMPT BUILDER
# ────────────────────────────────────────────────

LAYOUTS = [
    "Split-screen hero (image left, headline right) + 3-column services grid + dark footer",
    "Full-width cinematic hero with centred headline + wave divider + card services + testimonial strip",
    "Minimal typographic hero (giant business name) + bento grid services + bold CTA section",
    "Diagonal-cut hero with overlay text + icon services list + stats bar + contact form",
    "Dark hero with gradient text + glassmorphism service cards + light about section",
    "Asymmetric layout image-right + bullet services left + green CTA + social proof strip",
    "Magazine-style hero with large serif headline + colour-block service tiles + FAQ section",
]

def build_prompt(data, variation_index):
    name     = data.get('businessName') or data.get('business_name', 'My Business')
    btype    = data.get('businessType') or data.get('business_type', 'business')
    location = data.get('location', 'London')
    services = data.get('services', 'Professional Services')
    style    = data.get('style', 'modern')
    colors   = data.get('colors') or ["#2563eb", "#7c3aed", "#f8fafc"]

    if isinstance(colors, str):
        try:
            colors = json.loads(colors)
        except Exception:
            colors = ["#2563eb", "#7c3aed", "#f8fafc"]
    if not colors or len(colors) < 3:
        colors = ["#2563eb", "#7c3aed", "#f8fafc"]

    svc_list     = [s.strip() for s in str(services).split(',') if s.strip()]
    if not svc_list:
        svc_list = ["Premium Services", "Expert Consultation", "Quality Results"]

    img_kw, _, _ = get_category_info(btype)
    hero_img     = f"https://loremflickr.com/1920/1080/{img_kw}"
    card_img     = f"https://loremflickr.com/800/500/{img_kw}"
    layout       = LAYOUTS[variation_index % len(LAYOUTS)]

    STYLE_THEMES = [
        ("modern bold",    "dark hero, gradient accents, sharp cards"),
        ("professional",   "clean white layout, blue accents, trust badges"),
        ("creative",       "asymmetric layout, big typography, colour blocks"),
    ]
    theme_name, theme_desc = STYLE_THEMES[variation_index % 3]

    return f"""Output ONLY a complete single-file HTML website. Start with <!DOCTYPE html>. No markdown, no backticks.

Business: {name} | Industry: {btype} | Location: {location}
Primary: {colors[0]} | Secondary: {colors[1]} | Background: {colors[2]}
Services: {", ".join(svc_list[:5])}
Design theme: {theme_name} — {theme_desc}
Hero image URL: {hero_img}

Rules: CSS in <style>, Google Fonts CDN, Font Awesome 6 CDN, mobile-first, NO frameworks.
Include: sticky nav, hero with bg-image + CTA, services cards with FA icons, why-choose-us, testimonials, contact form, footer © {name}.
Write real persuasive copy for {btype} in {location}. No lorem ipsum.

<!DOCTYPE html>"""


# ────────────────────────────────────────────────
#  HTML GENERATION
# ────────────────────────────────────────────────

def generate_html(data, variation_index):
    global LAST_AI_ERROR, ACTIVE_MODEL

    if not gemini_client and not openai_client:
        LAST_AI_ERROR = (
            "No AI client configured. "
            "Please set GEMINI_API_KEY or OPENAI_API_KEY in your Vercel environment variables."
        )
        print(f"ERROR: {LAST_AI_ERROR}")
        return None

    prompt      = build_prompt(data, variation_index)
    temperature = round(0.7 + variation_index * 0.08, 2)

    try:
        raw = ""
        all_errors = []

        import time
        from google.genai import types as genai_types

        # ── Try Gemini models ──────────────────────────────────────────────
        if gemini_client:
            models_to_try = [ACTIVE_MODEL] + [m for m in GEMINI_CANDIDATES if m != ACTIVE_MODEL]

            for model_name in models_to_try:
                try:
                    print(f"  Trying Gemini {model_name} for variation {variation_index}...")
                    response = gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=0.7,
                            max_output_tokens=3500,
                            top_p=0.9,
                        )
                    )
                    raw = response.text.strip()
                    if raw:
                        ACTIVE_MODEL = model_name
                        print(f"  Gemini success: {model_name}")
                        break
                except Exception as me:
                    err_str = str(me)
                    err_up  = err_str.upper()
                    all_errors.append(f"{model_name}: {err_str[:120]}")
                    if "429" in err_up or "RESOURCE_EXHAUSTED" in err_up or "QUOTA" in err_up:
                        print(f"  {model_name} quota exhausted — next...")
                        continue
                    if "404" in err_up or "NOT_FOUND" in err_up:
                        print(f"  {model_name} not found — next...")
                        continue
                    if "503" in err_up or "OVERLOADED" in err_up:
                        time.sleep(3)
                        continue
                    print(f"  {model_name}: {me}")
                    continue

        # ── OpenAI: used if Gemini failed OR no Gemini key ─────────────────
        if not raw and openai_client:
            try:
                print(f"  Trying OpenAI gpt-4o-mini for variation {variation_index}...")
                resp = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=3500,
                )
                raw = resp.choices[0].message.content.strip()
                if raw:
                    print(f"  OpenAI success")
            except Exception as oe:
                all_errors.append(f"openai/gpt-4o-mini: {str(oe)[:120]}")
                print(f"  OpenAI failed: {oe}")

        # ── Nothing worked ─────────────────────────────────────────────────
        if not raw:
            errors_joined = str(all_errors)
            if "429" in errors_joined or "RESOURCE_EXHAUSTED" in errors_joined or "QUOTA" in errors_joined:
                LAST_AI_ERROR = (
                    "Your Gemini free-tier quota is exhausted (20 req/day limit). "
                    "Solutions: (1) Wait until tomorrow for quota reset, OR "
                    "(2) Add OPENAI_API_KEY to your Vercel env vars as a backup engine, OR "
                    "(3) Enable billing on your Google AI Studio project at aistudio.google.com."
                )
            else:
                LAST_AI_ERROR = f"All AI models failed. All errors: {all_errors}"
            return None

        # Clean markdown fences if model added them
        if "```html" in raw:
            raw = raw.split("```html", 1)[1].split("```", 1)[0].strip()
        elif raw.startswith("```"):
            raw = raw.lstrip("`").strip()
            if raw.startswith("html"):
                raw = raw[4:].strip()
            raw = raw.rsplit("```", 1)[0].strip()

        if not raw.lower().startswith("<!doctype"):
            raw = "<!DOCTYPE html>\n" + raw

        # Replace generic placeholder images with category images
        img_kw, _, _ = get_category_info(
            data.get("businessType") or data.get("business_type", "business")
        )
        raw = re.sub(
            r"https?://(?:source\.unsplash\.com|picsum\.photos|via\.placeholder\.com|placehold\.co)[^\s\"']*",
            f"https://loremflickr.com/1920/1080/{img_kw}",
            raw
        )

        print(f"  Variation {variation_index} done ({len(raw):,} chars)")
        LAST_AI_ERROR = ""
        return raw

    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} — {type(e).__name__}: {e}"
        print(f"  ERROR: {LAST_AI_ERROR}")
        traceback.print_exc()
        return None



# ────────────────────────────────────────────────
#  CONVERSION BANNER  (injected into final site)
# ────────────────────────────────────────────────

def inject_conversion_banner(html, site, slug, base_url):
    name              = site.get('business_name', 'Your Business')
    btype             = site.get('business_type', 'business')
    _, emoji, accent  = get_category_info(btype)
    dl_url            = f"{base_url}/download/{slug}"
    wa_url            = "https://wa.me/447700000000?text=I'd+like+to+launch+my+AI+website"

    banner = f"""
<style>
#_aicta{{
  position:fixed;bottom:0;left:0;right:0;z-index:999999;
  background:linear-gradient(135deg,#0f172a,#1e293b);
  color:#fff;padding:14px 24px;
  display:flex;align-items:center;justify-content:space-between;
  gap:12px;flex-wrap:wrap;
  box-shadow:0 -6px 32px rgba(0,0,0,.4);
  font-family:'Segoe UI',system-ui,sans-serif;
  font-size:14px;
}}
#_aicta .l{{display:flex;align-items:center;gap:10px}}
#_aicta .badge{{
  background:{accent};color:#fff;padding:3px 10px;
  border-radius:20px;font-size:11px;font-weight:700;
  letter-spacing:1px;text-transform:uppercase;white-space:nowrap;
}}
#_aicta .txt{{line-height:1.4}}
#_aicta .txt strong{{font-size:15px;display:block}}
#_aicta .r{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
#_aicta a,#_aicta button{{
  padding:10px 18px;border-radius:30px;font-weight:700;
  font-size:13px;cursor:pointer;border:none;text-decoration:none;
  display:inline-flex;align-items:center;gap:5px;
  transition:transform .2s,box-shadow .2s;white-space:nowrap;
}}
#_aicta a:hover,#_aicta button:hover{{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.3)}}
#_aicta .gbtn{{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}}
#_aicta .dbtn{{background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.2)!important}}
#_aicta .xbtn{{background:transparent;color:rgba(255,255,255,.45);font-size:18px;padding:4px 8px}}
body{{padding-bottom:78px!important}}
@media(max-width:600px){{#_aicta{{padding:10px 16px}}#_aicta .txt strong{{font-size:13px}}}}
</style>
<div id="_aicta">
  <div class="l">
    <span class="badge">AI Preview</span>
    <div class="txt">
      <strong>{name} &mdash; Your website is ready!</strong>
      Our team will finalise &amp; launch it for you &mdash; <strong style="color:#4ade80;display:inline">completely free</strong>
    </div>
  </div>
  <div class="r">
    <a href="{wa_url}" target="_blank" class="gbtn">Launch My Site Free</a>
    <a href="{dl_url}" class="dbtn">Download HTML</a>
    <button class="xbtn" onclick="document.getElementById('_aicta').remove();document.body.style.paddingBottom=0" title="Close">&#x2715;</button>
  </div>
</div>"""

    # Ensure UTF-8 charset is declared in the generated site
    if '<meta charset' not in html.lower():
        html = html.replace('<head>', '<head>\n  <meta charset="UTF-8">', 1)

    if "</body>" in html:
        return html.replace("</body>", f"{banner}\n</body>", 1)
    return html + banner


# ────────────────────────────────────────────────
#  HELPER: return HTML response with correct charset
# ────────────────────────────────────────────────

def html_response(content, status=200):
    return Response(
        content.encode('utf-8'),
        status=status,
        mimetype='text/html; charset=utf-8'
    )


# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

@app.route('/')
def home():
    return html_response("<h1>AI Website Builder — Backend OK</h1>")


@app.route('/api/list-models')
def list_models():
    """Call this to see exactly which models your API key can access."""
    if not gemini_client:
        return jsonify({"error": "Gemini client not initialised — check GEMINI_API_KEY"})
    try:
        models = gemini_client.models.list()
        names = sorted([
            m.name for m in models
            if "generateContent" in (m.supported_actions or [])
               or "generateContent" in str(getattr(m, "supported_generation_methods", ""))
        ])
        # Also include raw model objects for full detail
        raw = [str(m.name) for m in gemini_client.models.list()]
        return jsonify({
            "generate_content_models": names,
            "all_models": raw,
            "active_model": ACTIVE_MODEL,
            "candidates_being_tried": GEMINI_CANDIDATES,
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/health')
def health():
    return jsonify({
        "status":       "ok",
        "active_model": ACTIVE_MODEL or "none",
        "gemini":       bool(gemini_client),
        "openai":       bool(openai_client),
        "database":     bool(DATABASE_URL),
        "last_error":   LAST_AI_ERROR or "none",
    })


@app.route('/api/debug')
def debug():
    return jsonify({
        "GEMINI_KEY_set":   bool(GEMINI_KEY),
        "OPENAI_KEY_set":   bool(OPENAI_KEY),
        "active_model":     ACTIVE_MODEL,
        "gemini_ready":     bool(gemini_client),
        "openai_ready":     bool(openai_client),
        "database_url_set": bool(DATABASE_URL),
        "last_ai_error":    LAST_AI_ERROR or "none",
    })


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


# ── Step 2: Poll + trigger AI ────────────────────
@app.route('/api/status/<slug>')
def check_status(slug):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()

        if not site:
            conn.close()
            return jsonify({"status": "NOT_FOUND"}), 404

        current_status = site['status']

        # Generate 1 design fast on first poll
        if current_status == 'STARTING':
            site_data = dict(site)

            cur.execute(
                "UPDATE sites SET status='GENERATING', message='AI is building your website...' WHERE slug=%s",
                (slug,)
            )
            conn.commit()

            html = generate_html(site_data, 0)

            if not html:
                err = LAST_AI_ERROR or "AI generation failed"
                cur.execute(
                    "UPDATE sites SET status='FAILED', message=%s WHERE slug=%s",
                    (err, slug)
                )
                conn.commit()
                conn.close()
                return jsonify({"status": "FAILED", "message": err})

            cur.execute(
                "DELETE FROM variations WHERE site_slug=%s AND variation_index=%s",
                (slug, 0)
            )
            cur.execute(
                "INSERT INTO variations (site_slug, variation_index, html_content) VALUES (%s,%s,%s)",
                (slug, 0, html)
            )

            cur.execute(
                "UPDATE sites SET status='AWAITING_SELECTION', message='Your website is ready!' WHERE slug=%s",
                (slug,)
            )
            conn.commit()
            current_status = 'AWAITING_SELECTION'

        elif current_status == 'GENERATING':
            # Still running — just return current state, frontend will poll again
            pass

        # Fetch variation URLs
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
    data  = request.get_json() or {}
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

        base       = request.host_url.rstrip('/')
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




# ── LONG POLL: generate all 3, hold connection open until done ───────────────
@app.route('/api/generate-all/<slug>')
def generate_all(slug):
    """
    Long-poll endpoint. Frontend calls this ONCE.
    Server generates all 3 designs in parallel threads,
    then responds with the results when all are done.
    Vercel Pro timeout: 300s. Vercel Hobby: 60s.
    """
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()

        if not site:
            conn.close()
            return jsonify({"success": False, "message": "Site not found"}), 404

        # If already done, return immediately
        if site['status'] == 'AWAITING_SELECTION':
            cur.execute(
                "SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",
                (slug,)
            )
            base = request.host_url.rstrip('/')
            variations = [
                {"id": r["variation_index"],
                 "url": f"{base}/view-design/{slug}/{r['variation_index']}"}
                for r in cur.fetchall()
            ]
            conn.close()
            return jsonify({
                "success": True,
                "status": "AWAITING_SELECTION",
                "selectionUrl": f"{base}/select/{slug}",
                "variations": variations
            })

        cur.execute(
            "UPDATE sites SET status='GENERATING_ALL', message='Building 3 designs...' WHERE slug=%s",
            (slug,)
        )
        conn.commit()
        conn.close()

        site_data = dict(site)
        import concurrent.futures

        # Generate all 3 in parallel threads
        def gen(idx):
            return idx, generate_html(site_data, idx)

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            for idx, html in ex.map(lambda i: gen(i), range(3)):
                results[idx] = html

        # Save results to DB
        conn2 = get_db()
        cur2  = conn2.cursor()

        success_count = 0
        for idx in range(3):
            html = results.get(idx)
            if html:
                cur2.execute(
                    "DELETE FROM variations WHERE site_slug=%s AND variation_index=%s",
                    (slug, idx)
                )
                cur2.execute(
                    "INSERT INTO variations (site_slug, variation_index, html_content) VALUES (%s,%s,%s)",
                    (slug, idx, html)
                )
                success_count += 1

        if success_count == 0:
            err = LAST_AI_ERROR or "All 3 generations failed"
            cur2.execute(
                "UPDATE sites SET status='FAILED', message=%s WHERE slug=%s",
                (err, slug)
            )
            conn2.commit()
            conn2.close()
            return jsonify({"success": False, "message": err})

        cur2.execute(
            "UPDATE sites SET status='AWAITING_SELECTION', message='All designs ready!' WHERE slug=%s",
            (slug,)
        )
        conn2.commit()

        base = request.host_url.rstrip('/')
        cur2.execute(
            "SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",
            (slug,)
        )
        import psycopg2.extras as _pge
        cur2_r = conn2.cursor(cursor_factory=RealDictCursor)
        cur2_r.execute(
            "SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",
            (slug,)
        )
        variations = [
            {"id": r["variation_index"],
             "url": f"{base}/view-design/{slug}/{r['variation_index']}"}
            for r in cur2_r.fetchall()
        ]
        conn2.close()

        return jsonify({
            "success":      True,
            "status":       "AWAITING_SELECTION",
            "selectionUrl": f"{base}/select/{slug}",
            "variations":   variations,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

# ── Serve final site ─────────────────────────────
@app.route('/s/<slug>')
def show_site(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if row:
            return html_response(row[0])
        return html_response("<h1>404 — Site not found</h1>", 404)
    except Exception as e:
        return html_response(f"<h1>Server error: {e}</h1>", 500)


# ── View individual variation ────────────────────
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
        if row:
            return html_response(row[0])
        return html_response("<h1>Variation not found</h1>", 404)
    except Exception as e:
        return html_response(f"<h1>Error: {e}</h1>", 500)


# ── Download ZIP ─────────────────────────────────
@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return html_response("<h1>Not found or not finalised yet</h1>", 404)

        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0].encode('utf-8'))
        buf.seek(0)
        return send_file(
            buf, mimetype='application/zip',
            as_attachment=True,
            download_name=f"{slug}_website.zip"
        )
    except Exception as e:
        return html_response(f"<h1>Download error: {e}</h1>", 500)


# ── Design selection page ────────────────────────
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
            return html_response("<h1>Not found</h1>", 404)

        name              = site['business_name'] or 'Your Business'
        btype             = site['business_type']  or 'business'
        _, emoji, accent  = get_category_info(btype)
        base              = request.host_url.rstrip('/')

        cards = ""
        for v in variations:
            i = v['variation_index']
            cards += f"""
            <div class="card">
              <div class="card-label">
                <span class="badge">Design {i+1}</span>
                <span class="sub">AI Generated Layout</span>
              </div>
              <div class="preview-wrap">
                <iframe src="{base}/view-design/{slug}/{i}" loading="lazy"></iframe>
                <div class="overlay" onclick="pick('{slug}',{i})"></div>
              </div>
              <div class="card-foot">
                <button class="pick-btn" onclick="pick('{slug}',{i})">Choose This Design</button>
                <a href="{base}/view-design/{slug}/{i}" target="_blank" class="prev-btn">Full Preview</a>
              </div>
            </div>"""

        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Choose Your Design &mdash; {name}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Inter',sans-serif;background:#f0f4ff;color:#0f172a}}
    header{{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.96);
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
    .hero h2{{font-size:clamp(1.8rem,4vw,3rem);font-weight:900;
      letter-spacing:-.02em;margin-bottom:10px}}
    .hero p{{color:rgba(255,255,255,.65);font-size:1rem;max-width:500px;margin:0 auto}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
      gap:24px;max-width:1280px;margin:40px auto 60px;padding:0 24px}}
    .card{{background:#fff;border-radius:20px;overflow:hidden;
      box-shadow:0 10px 40px rgba(0,0,0,.08);transition:.3s}}
    .card:hover{{transform:translateY(-6px);box-shadow:0 24px 60px rgba(0,0,0,.13)}}
    .card-label{{padding:16px 20px 12px;display:flex;align-items:center;gap:10px}}
    .badge{{background:{accent};color:#fff;font-size:10px;font-weight:700;
      padding:3px 10px;border-radius:20px;text-transform:uppercase;letter-spacing:.5px}}
    .sub{{color:#94a3b8;font-size:12px}}
    .preview-wrap{{position:relative;height:440px;overflow:hidden}}
    .preview-wrap iframe{{width:100%;height:100%;border:none;pointer-events:none;
      transform:scale(.95);transform-origin:top center}}
    .overlay{{position:absolute;inset:0;cursor:pointer}}
    .overlay:hover{{background:rgba(79,70,229,.04)}}
    .card-foot{{padding:16px 20px;display:flex;gap:8px}}
    .pick-btn{{flex:1;background:linear-gradient(135deg,{accent},#818cf8);
      color:#fff;border:none;padding:12px;border-radius:12px;
      font-size:13px;font-weight:700;cursor:pointer;transition:.2s}}
    .pick-btn:hover{{opacity:.9;transform:translateY(-1px)}}
    .prev-btn{{background:#f1f5f9;color:#475569;padding:12px 16px;
      border-radius:12px;text-decoration:none;font-size:12px;font-weight:600}}
    #loader{{display:none;position:fixed;inset:0;background:rgba(15,23,42,.85);
      backdrop-filter:blur(8px);z-index:9999;flex-direction:column;
      align-items:center;justify-content:center;color:#fff;text-align:center}}
    .ring{{width:60px;height:60px;border:4px solid rgba(255,255,255,.15);
      border-top-color:{accent};border-radius:50%;
      animation:spin .8s linear infinite;margin-bottom:20px}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    #loader h3{{font-size:1.4rem;font-weight:700}}
  </style>
</head>
<body>
  <header>
    <h1>{name}</h1>
    <a href="{base}/build-with-ai" class="back">&larr; Start Over</a>
  </header>
  <div class="hero">
    <div class="tag">AI Generation Complete</div>
    <h2>Choose Your Favourite Design</h2>
    <p>3 unique layouts built for {name} &mdash; pick the one you love.</p>
  </div>
  <div class="grid">{cards}</div>
  <div id="loader">
    <div class="ring"></div>
    <h3>Finalising your website&hellip;</h3>
  </div>
  <script>
    async function pick(slug, index) {{
      document.getElementById('loader').style.display = 'flex';
      try {{
        const r = await fetch('{base}/api/select-design', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{slug, designIndex: index}})
        }});
        const d = await r.json();
        if (d.success) {{
          window.location = d.previewUrl;
        }} else {{
          alert('Error: ' + (d.message || 'Unknown error'));
          document.getElementById('loader').style.display = 'none';
        }}
      }} catch(e) {{
        alert('Network error: ' + e.message);
        document.getElementById('loader').style.display = 'none';
      }}
    }}
  </script>
</body>
</html>"""
        return html_response(page)

    except Exception as e:
        traceback.print_exc()
        return html_response(f"<h1>Error: {e}</h1>", 500)


if __name__ == '__main__':
    print("AI Website Builder starting...")
    app.run(host='0.0.0.0', port=5000, debug=True)
