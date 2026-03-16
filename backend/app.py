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

# Curated Unsplash photo IDs — correct category images guaranteed
# Format per key: (hero_photo_id, card_photo_id, emoji, accent_color)
CATEGORY_IMAGES = {
    "plumber":      ("1504328345596-d9e5b6f2e9fc", "1558618666-fcd25c85cd64", "💧", "#0ea5e9"),
    "electrician":  ("1621905251189-08b45d6a269e", "1558618666-fcd25c85cd64", "⚡", "#f59e0b"),
    "restaurant":   ("1517248135467-4c7edcad34c4", "1414235077428-338989a2e8c0", "🍽️", "#ef4444"),
    "law":          ("1589578527966-fdac0f44566c", "1505664194779-8beaceb222a3", "⚖️", "#1e3a5f"),
    "consulting":   ("1552664730-d307ca884978", "1542744173-05336fcc7ad4", "📊", "#6366f1"),
    "fitness":      ("1534438327776-3c94b817a2b3", "1540497077202-7c8a3999166f", "💪", "#10b981"),
    "realestate":   ("1560518883-ce09059eeffa", "1570129477492-45c003edd12a", "🏠", "#f97316"),
    "agency":       ("1553028826-f4804a6dba3b", "1542744094-24638eff58bb", "🎨", "#8b5cf6"),
    "shoes":        ("1542291026-7eec264c27ff", "1542291026-7eec264c27ff", "👟", "#ec4899"),
    "beauty":       ("1560066984-138daab7a254", "1522337360826-35f62d3be0ba", "💅", "#f43f5e"),
    "medical":      ("1551076805-e1869033e561", "1576091160399-112ba8d25d1d", "🏥", "#06b6d4"),
    "education":    ("1503676260728-1c00da094a0b", "1456513080510-7bf3a84b82f8", "📚", "#84cc16"),
    "tech":         ("1518770660439-4636190af475", "1517430816045-df4b7de11d1d", "💻", "#3b82f6"),
    "construction": ("1504307651254-35680f356dfd", "1503387762-592deb58ef4e", "🏗️", "#78716c"),
    "cleaning":     ("1581578731548-c64695cc6952", "1563453392212-326f5e854473", "✨", "#14b8a6"),
    "photography":  ("1452780212441-5c1549ab4a3c", "1542038374332-f75b89a6a556", "📸", "#a855f7"),
    "other":        ("1497366216548-37526070297c", "1497366811353-6870744d04b2", "🏢", "#475569"),
}

def get_category_info(business_type):
    """Returns (hero_id, card_id, emoji, accent_color)."""
    bt = (business_type or "other").lower().strip()
    for key in CATEGORY_IMAGES:
        if key in bt:
            return CATEGORY_IMAGES[key]
    return CATEGORY_IMAGES["other"]

def get_images(business_type):
    """Returns (hero_url, card_url, emoji, accent_color)."""
    hero_id, card_id, emoji, accent = get_category_info(business_type)
    hero = f"https://images.unsplash.com/photo-{hero_id}?w=1920&q=80&fit=crop&auto=format"
    card = f"https://images.unsplash.com/photo-{card_id}?w=800&q=80&fit=crop&auto=format"
    return hero, card, emoji, accent

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
#  AI PROMPT BUILDER  — 3 distinct design briefs
# ────────────────────────────────────────────────

def build_prompt(data, variation_index):
    name     = data.get('businessName') or data.get('business_name', 'My Business')
    btype    = data.get('businessType') or data.get('business_type', 'business')
    location = data.get('location', 'London')
    services = data.get('services', 'Professional Services')
    colors   = data.get('colors') or ["#2563eb", "#7c3aed", "#f8fafc"]

    if isinstance(colors, str):
        try:    colors = json.loads(colors)
        except: colors = ["#2563eb", "#7c3aed", "#f8fafc"]
    if not colors or len(colors) < 3:
        colors = ["#2563eb", "#7c3aed", "#f8fafc"]

    svc_list = [s.strip() for s in str(services).split(',') if s.strip()]
    if not svc_list:
        svc_list = ["Professional Services", "Expert Consultation", "Quality Results"]

    hero_url, card_url, _, _ = get_images(btype)
    p, s, bg = colors[0], colors[1], colors[2]
    svc_items = chr(10).join(f"- {sv}" for sv in svc_list)

    DESIGNS = [
        {
            "style": "DARK BOLD HERO",
            "font":  "Montserrat",
            "nav":   "fixed, black background rgba(0,0,0,0.95), white logo and links",
            "hero":  f"full viewport height, background-image url('{hero_url}') with dark overlay 0.6 opacity, centered white text, h1 font-size 4.5rem font-weight 900, one CTA button background {p} color white border-radius 50px padding 18px 48px",
            "cards": f"white background, box-shadow 0 4px 24px rgba(0,0,0,0.08), border-radius 12px, icon color {p}, hover translateY(-6px)",
            "why_bg": f"background {p} color white",
            "footer": "background #0a0a0a color rgba(255,255,255,0.6)",
        },
        {
            "style": "CLEAN CORPORATE SPLIT HERO",
            "font":  "Inter",
            "nav":   f"fixed, white background, border-bottom 1px solid #e5e7eb, logo color {p}",
            "hero":  f"CSS grid 1fr 1fr no padding-top: LEFT column background {p} padding 80px flex column justify-center white h1 3.5rem font-weight 800 CTA button white color {p}; RIGHT column background-image url('{hero_url}') cover no-repeat min-height 100vh",
            "cards": f"white background, border 1px solid #e5e7eb, border-radius 8px, icon color {p}, hover box-shadow increase",
            "why_bg": "background #1e293b color white",
            "footer": "background #1f2937 color rgba(255,255,255,0.6)",
        },
        {
            "style": "VIBRANT GRADIENT CREATIVE",
            "font":  "Poppins",
            "nav":   f"fixed, gradient background linear-gradient(135deg, {p}, {s}), white logo and links",
            "hero":  f"gradient background linear-gradient(135deg, {p}, {s}) min-height 92vh flex center, h1 white font-size 5rem font-weight 900 letter-spacing -3px, TWO buttons: solid white color {p} + outline white transparent",
            "cards": f"white background, border-top 4px solid {p}, border-radius 16px, icon inside filled circle {p}, hover translateY(-6px)",
            "why_bg": f"background linear-gradient(135deg, {p}22, {s}22)",
            "footer": "background #0f172a color rgba(255,255,255,0.6)",
        },
    ]

    d = DESIGNS[variation_index % 3]

    prompt = (
        "You are an expert front-end developer. Output ONLY raw HTML starting with <!DOCTYPE html>."
        " No markdown, no backticks, no explanation text."
        " All CSS in one <style> tag. Load ONLY Google Fonts + Font Awesome 6.5 from CDN."
        " NO Bootstrap, NO Tailwind. Mobile responsive with media queries.\n\n"
        f"BUSINESS: {name} | Industry: {btype} | Location: {location}\n"
        f"Primary colour: {p} | Secondary: {s}\n"
        f"Hero image: {hero_url}\n"
        f"Card image: {card_url}\n"
        f"\nSERVICES (one card each, exact names):\n{svc_items}\n"
        f"\nDESIGN STYLE: {d['style']}\n"
        f"Font: {d['font']} from Google Fonts\n"
        f"Navigation: {d['nav']}\n"
        f"Hero: {d['hero']}\n"
        f"Service cards: {d['cards']}\n"
        f"Why Choose Us: {d['why_bg']}, 4 tiles: 500+ Clients / 10 Yrs Experience / 4.9 Star Rating / 24/7 Support\n"
        f"Footer: {d['footer']}\n"
        "\nREQUIRED SECTIONS (all mandatory):\n"
        f"1. Fixed nav: logo={name}, links=Services/About/Reviews/Contact, CTA button Get Quote\n"
        "2. Hero section as described above\n"
        "3. Services grid: one card per service with Font Awesome icon + exact service name + 2-line description\n"
        f"4. About: image left + 2 paragraphs about {name} in {location} right\n"
        "5. Why Choose Us: 4 stat tiles on coloured bg\n"
        "6. Testimonials: 3 cards with 5 stars, quote, name\n"
        "7. Contact form: name/email/phone/message + submit\n"
        f"8. Footer: copyright {name}, {location}\n"
        f"\nWrite real copy mentioning {name} and {location}. No lorem ipsum.\n"
        "\n<!DOCTYPE html>"
    )
    return prompt


# ────────────────────────────────────────────────
#  AI HTML GENERATION
# ────────────────────────────────────────────────

def generate_html(data, variation_index):
    global LAST_AI_ERROR, ACTIVE_MODEL

    if not gemini_client and not openai_client:
        LAST_AI_ERROR = "No AI key set. Add GEMINI_API_KEY or OPENAI_API_KEY in Vercel env vars."
        return None

    prompt = build_prompt(data, variation_index)

    try:
        raw        = ""
        all_errors = []

        if gemini_client:
            import time
            from google.genai import types as genai_types
            models_to_try = [ACTIVE_MODEL] + [m for m in GEMINI_CANDIDATES if m != ACTIVE_MODEL]

            for model_name in models_to_try:
                try:
                    print(f"  [{variation_index}] Trying {model_name}...")
                    resp = gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=0.8,
                            max_output_tokens=8192,
                            top_p=0.95,
                        )
                    )
                    raw = resp.text.strip()
                    if raw:
                        ACTIVE_MODEL = model_name
                        print(f"  [{variation_index}] Gemini OK ({model_name}, {len(raw):,} chars)")
                        break
                except Exception as me:
                    eu = str(me).upper()
                    all_errors.append(f"{model_name}: {str(me)[:100]}")
                    if any(x in eu for x in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                        print(f"  [{variation_index}] {model_name} quota exhausted")
                        continue
                    if any(x in eu for x in ["404", "NOT_FOUND"]):
                        print(f"  [{variation_index}] {model_name} not found")
                        continue
                    if any(x in eu for x in ["503", "OVERLOADED"]):
                        time.sleep(2)
                        continue
                    print(f"  [{variation_index}] {model_name}: {me}")
                    continue

        if not raw and openai_client:
            try:
                print(f"  [{variation_index}] Trying OpenAI...")
                resp = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                    max_tokens=7000,
                )
                raw = resp.choices[0].message.content.strip()
                if raw:
                    print(f"  [{variation_index}] OpenAI OK ({len(raw):,} chars)")
            except Exception as oe:
                all_errors.append(f"openai: {str(oe)[:100]}")
                print(f"  [{variation_index}] OpenAI failed: {oe}")

        if not raw:
            errs = str(all_errors)
            if any(x in errs for x in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                LAST_AI_ERROR = (
                    "Gemini quota exhausted. Fix: (1) Wait 24h for reset, "
                    "(2) Add OPENAI_API_KEY to Vercel env vars, "
                    "(3) Enable billing at aistudio.google.com"
                )
            else:
                LAST_AI_ERROR = f"All AI failed: {all_errors}"
            return None

        if "```html" in raw:
            raw = raw.split("```html", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

        if not raw.lower().startswith("<!doctype"):
            raw = "<!DOCTYPE html>\n" + raw

        if '<meta charset' not in raw.lower():
            raw = raw.replace('<head>', '<head>\n<meta charset="UTF-8">', 1)

        hero_url, _, _, _ = get_images(
            data.get('businessType') or data.get('business_type', 'business')
        )
        import re as _re
        raw = _re.sub(
            r'https?://(?:source\.unsplash\.com|picsum\.photos|via\.placeholder\.com|loremflickr\.com)[^\s"\']*',
            hero_url,
            raw
        )

        LAST_AI_ERROR = ""
        return raw

    except Exception as e:
        LAST_AI_ERROR = f"generate_html error: {type(e).__name__}: {e}"
        traceback.print_exc()
        return None


# ────────────────────────────────────────────────
#  CONVERSION BANNER  (injected into final site)
# ────────────────────────────────────────────────

def inject_conversion_banner(html, site, slug, base_url):
    name              = site.get('business_name', 'Your Business')
    btype             = site.get('business_type', 'business')
    _hero_id, _card_id, emoji, accent = get_category_info(btype)
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




# ── Generate ONE design per request (Vercel-safe, <30s each) ─────────────────
@app.route('/api/generate-one/<slug>/<int:idx>')
def generate_one(slug, idx):
    """
    Generates exactly one design variation and saves it to DB.
    Frontend calls this 3 times (idx=0,1,2) sequentially.
    Each call is independent — safe within Vercel 60s timeout.
    """
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()
        conn.close()

        if not site:
            return jsonify({"success": False, "message": "Site not found"}), 404

        if idx not in (0, 1, 2):
            return jsonify({"success": False, "message": "idx must be 0, 1 or 2"}), 400

        print(f"[{slug}] Generating design {idx}...")
        html = generate_html(dict(site), idx)

        if not html:
            err = LAST_AI_ERROR or f"Design {idx} generation failed"
            return jsonify({"success": False, "message": err})

        # Save to DB
        conn2 = get_db()
        cur2  = conn2.cursor()
        cur2.execute("DELETE FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        cur2.execute(
            "INSERT INTO variations (site_slug, variation_index, html_content) VALUES (%s,%s,%s)",
            (slug, idx, html)
        )

        # If this is the last design, mark ready
        if idx == 2:
            cur2.execute(
                "UPDATE sites SET status='AWAITING_SELECTION', message='All 3 designs ready!' WHERE slug=%s",
                (slug,)
            )
        else:
            cur2.execute(
                "UPDATE sites SET status=%s, message=%s WHERE slug=%s",
                (f'DONE_{idx}', f'Design {idx+1} of 3 ready', slug)
            )

        conn2.commit()
        conn2.close()

        base = request.host_url.rstrip('/')
        return jsonify({
            "success":       True,
            "variation_id":  idx,
            "preview_url":   f"{base}/view-design/{slug}/{idx}",
            "all_done":      idx == 2,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500




# ── Register job ──────────────────────────────────────────────────────────────
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
              (slug,business_name,business_type,location,services,style,colors,status,message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'STARTING','Ready')
            ON CONFLICT (slug) DO NOTHING
        """, (slug, data.get('businessName'), data.get('businessType','other'),
              data.get('location',''), data.get('services',''),
              data.get('style','modern'), data.get('colors',[])))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "slug": slug})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Select design ─────────────────────────────────────────────────────────────
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
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s",
                    (slug, int(index)))
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
            VALUES (%s,%s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content=EXCLUDED.html_content
        """, (slug, final_html))
        cur.execute("UPDATE sites SET status='COMPLETED',message='Website ready' WHERE slug=%s",(slug,))
        conn.commit()
        conn.close()
        return jsonify({"success":True,"previewUrl":f"{base}/s/{slug}","downloadUrl":f"{base}/download/{slug}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Serve final site ──────────────────────────────────────────────────────────
@app.route('/s/<slug>')
def show_site(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if row:
            return Response(row[0].encode('utf-8'), mimetype='text/html; charset=utf-8')
        return Response("<h1>404 — Not found</h1>", status=404, mimetype='text/html')
    except Exception as e:
        return Response(f"<h1>Error: {e}</h1>", status=500, mimetype='text/html')


# ── View one variation ────────────────────────────────────────────────────────
@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s",(slug,idx))
        row = cur.fetchone()
        conn.close()
        if row:
            return Response(row[0].encode('utf-8'), mimetype='text/html; charset=utf-8')
        return Response("<h1>Not found</h1>", status=404, mimetype='text/html')
    except Exception as e:
        return Response(f"<h1>Error: {e}</h1>", status=500, mimetype='text/html')


# ── Download ZIP ──────────────────────────────────────────────────────────────
@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s",(slug,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return Response("<h1>Not found</h1>", status=404, mimetype='text/html')
        buf = BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0].encode('utf-8'))
        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f"{slug}_website.zip")
    except Exception as e:
        return Response(f"<h1>Error: {e}</h1>", status=500, mimetype='text/html')


# ── Design selection page ─────────────────────────────────────────────────────
@app.route('/select/<slug>')
def select_page(slug):
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s",(slug,))
        site = cur.fetchone()
        cur.execute("SELECT variation_index FROM variations WHERE site_slug=%s ORDER BY variation_index",(slug,))
        variations = cur.fetchall()
        conn.close()
        if not site:
            return Response("<h1>Not found</h1>", status=404, mimetype='text/html')
        name  = site['business_name'] or 'Your Business'
        btype = site['business_type'] or 'business'
        _,_,emoji,accent = get_category_info(btype)
        base  = request.host_url.rstrip('/')
        cards = ""
        for v in variations:
            i = v['variation_index']
            cards += f"""<div class="card">
              <div class="clabel"><span class="badge">Design {i+1}</span></div>
              <div class="pw"><iframe src="{base}/view-design/{slug}/{i}" loading="lazy"></iframe>
              <div class="ov" onclick="pick('{slug}',{i})"></div></div>
              <div class="cf">
                <button class="pb" onclick="pick('{slug}',{i})">Choose This Design</button>
                <a href="{base}/view-design/{slug}/{i}" target="_blank" class="pvb">Full Preview</a>
              </div></div>"""
        page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Choose Your Design</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Inter',sans-serif;background:#f0f4ff}}
header{{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.96);backdrop-filter:blur(12px);border-bottom:1px solid rgba(0,0,0,.07);padding:16px 32px;display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:1rem;font-weight:700}}.back{{color:#64748b;font-size:13px;font-weight:600;padding:8px 16px;border-radius:20px;border:1px solid #e2e8f0;text-decoration:none}}
.hero{{text-align:center;padding:60px 24px 48px;background:linear-gradient(135deg,#0f172a,#1e3a5f);color:#fff}}
.tag{{display:inline-block;background:{accent};color:#fff;padding:6px 18px;border-radius:30px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:20px}}
.hero h2{{font-size:clamp(1.8rem,4vw,3rem);font-weight:900;letter-spacing:-.02em;margin-bottom:10px}}
.hero p{{color:rgba(255,255,255,.65);font-size:1rem;max-width:500px;margin:0 auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px;max-width:1280px;margin:40px auto 60px;padding:0 24px}}
.card{{background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 10px 40px rgba(0,0,0,.08);transition:.3s}}
.card:hover{{transform:translateY(-6px);box-shadow:0 24px 60px rgba(0,0,0,.13)}}
.clabel{{padding:16px 20px 12px;display:flex;align-items:center;gap:10px}}
.badge{{background:{accent};color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:20px;text-transform:uppercase}}
.pw{{position:relative;height:440px;overflow:hidden}}.pw iframe{{width:100%;height:100%;border:none;pointer-events:none;transform:scale(.95);transform-origin:top center}}
.ov{{position:absolute;inset:0;cursor:pointer}}.ov:hover{{background:rgba(79,70,229,.04)}}
.cf{{padding:16px 20px;display:flex;gap:8px}}
.pb{{flex:1;background:linear-gradient(135deg,{accent},#818cf8);color:#fff;border:none;padding:12px;border-radius:12px;font-size:13px;font-weight:700;cursor:pointer}}
.pb:hover{{opacity:.9;transform:translateY(-1px)}}
.pvb{{background:#f1f5f9;color:#475569;padding:12px 16px;border-radius:12px;text-decoration:none;font-size:12px;font-weight:600}}
#loader{{display:none;position:fixed;inset:0;background:rgba(15,23,42,.85);backdrop-filter:blur(8px);z-index:9999;flex-direction:column;align-items:center;justify-content:center;color:#fff;text-align:center}}
.ring{{width:60px;height:60px;border:4px solid rgba(255,255,255,.15);border-top-color:{accent};border-radius:50%;animation:spin .8s linear infinite;margin-bottom:20px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
#loader h3{{font-size:1.4rem;font-weight:700}}
</style></head><body>
<header><h1>{name}</h1><a href="/" class="back">&larr; Home</a></header>
<div class="hero"><div class="tag">AI Generation Complete</div>
<h2>Choose Your Favourite Design</h2>
<p>3 unique layouts built for {name}. Pick the one you love.</p></div>
<div class="grid">{cards}</div>
<div id="loader"><div class="ring"></div><h3>Finalising your website&hellip;</h3></div>
<script>
async function pick(slug,index){{
  document.getElementById('loader').style.display='flex';
  try{{
    const r=await fetch('{base}/api/select-design',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{slug,designIndex:index}})}});
    const d=await r.json();
    if(d.success){{window.location=d.previewUrl}}
    else{{alert('Error: '+(d.message||'Unknown'));document.getElementById('loader').style.display='none'}}
  }}catch(e){{alert('Error: '+e.message);document.getElementById('loader').style.display='none'}}
}}
</script></body></html>"""
        return Response(page.encode('utf-8'), mimetype='text/html; charset=utf-8')
    except Exception as e:
        traceback.print_exc()
        return Response(f"<h1>Error: {e}</h1>", status=500, mimetype='text/html')


if __name__ == '__main__':
    print("AI Website Builder starting...")
    app.run(host='0.0.0.0', port=5000, debug=True)
