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
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

load_dotenv()

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=False,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    methods=["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    max_age=86400,
)


@app.after_request
def _force_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers.pop("X-Frame-Options", None)
    csp = response.headers.get("Content-Security-Policy", "")
    if "frame-ancestors" in csp:
        parts = [p.strip() for p in csp.split(";") if p.strip() and "frame-ancestors" not in p]
        if parts:
            response.headers["Content-Security-Policy"] = "; ".join(parts)
        else:
            response.headers.pop("Content-Security-Policy", None)
    return response


def _corsify(resp):
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    resp.headers.setdefault("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS, PATCH")
    resp.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Accept")
    return resp


@app.errorhandler(Exception)
def _handle_any_exception(exc):
    if isinstance(exc, HTTPException):
        resp = exc.get_response()
        return _corsify(resp)
    traceback.print_exc()
    safe = str(exc) if app.debug else "Server error — see logs."
    r = jsonify({"success": False, "message": safe})
    r.status_code = 500
    return _corsify(r)


_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if _SERVERLESS:
    UPLOAD_FOLDER = os.path.join("/tmp", "awake_uploads", "templates")
else:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "templates")
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

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
    bt = (business_type or "other").lower().strip()
    for key in CATEGORY_IMAGES:
        if key in bt:
            return CATEGORY_IMAGES[key]
    return CATEGORY_IMAGES["other"]

def get_images(business_type):
    hero_id, card_id, emoji, accent = get_category_info(business_type)
    hero = f"https://images.unsplash.com/photo-{hero_id}?w=1920&q=80&fit=crop&auto=format"
    card = f"https://images.unsplash.com/photo-{card_id}?w=800&q=80&fit=crop&auto=format"
    return hero, card, emoji, accent

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL missing")
        return
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                slug TEXT PRIMARY KEY, business_name TEXT, business_type TEXT,
                location TEXT, services TEXT, style TEXT, colors TEXT[],
                status TEXT, message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS variations (
                id SERIAL PRIMARY KEY,
                site_slug TEXT REFERENCES sites(slug) ON DELETE CASCADE,
                variation_index INT, html_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS final_sites (
                site_slug TEXT PRIMARY KEY REFERENCES sites(slug) ON DELETE CASCADE,
                html_content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'variations_slug_idx_key'
                ) THEN
                    ALTER TABLE variations ADD CONSTRAINT variations_slug_idx_key UNIQUE (site_slug, variation_index);
                END IF;
            END$$;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS template_submissions (
                id SERIAL PRIMARY KEY, name TEXT, email TEXT, template_name TEXT,
                category TEXT, preview_url TEXT, file_path TEXT, description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close(); conn.close()
        print("DB ready")
    except Exception as e:
        print(f"DB init error: {e}")

_init_db_ran = False

def _lazy_init_db():
    global _init_db_ran
    if _init_db_ran:
        return
    _init_db_ran = True
    with app.app_context():
        init_db()

def _route_needs_migrations(path):
    if not path:
        return False
    base = path.rstrip('/') or '/'
    if base in ('/health', '/api/health'):
        return False
    if path.startswith('/api/'):
        return True
    if path.startswith('/view-design/'):
        return True
    if path.startswith('/s/'):
        return True
    if path.startswith('/download/'):
        return True
    return False

@app.before_request
def _run_migrations_once():
    if request.method == 'OPTIONS':
        return
    if not _route_needs_migrations(request.path):
        return
    _lazy_init_db()

GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY") or
    os.getenv("GOOGLE_API_KEY") or
    os.getenv("GOOGLE_GEMINI_KEY") or ""
)

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-2.0-flash-lite",
]

gemini_client = None
ACTIVE_MODEL = "gemini-2.0-flash"
LAST_AI_ERROR = ""

if GEMINI_KEY:
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types
        gemini_client = google_genai.Client(api_key=GEMINI_KEY)
        print(f"Gemini ready — default model: {ACTIVE_MODEL}")
    except ImportError:
        print("ERROR: run  pip install google-genai")
    except Exception as e:
        print(f"Gemini error: {e}")
else:
    print("WARNING: GEMINI_API_KEY not set")


def build_prompt(data, variation_index, base_url=""):
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
    p, s = colors[0], colors[1]

    DESIGNS = [
        {
            "name": "Modern Dark Bold",
            "font": "Montserrat",
            "nav":  f"position fixed, background rgba(0,0,0,0.96), white logo '{name}', white nav links",
            "hero": f"100vh height, background-image url('{hero_url}') cover center, dark overlay rgba(0,0,0,0.65), centered white text, h1 4.5rem font-weight 900, subtext 1.2rem, large {p} CTA button",
            "about_media": f"background-image url('{card_url}') cover center, border-radius 20px, box-shadow 0 20px 40px rgba(0,0,0,0.1)",
        },
        {
            "name": "Clean Split Corporate",
            "font": "Inter",
            "nav":  f"position fixed, background #ffffff, border-bottom 1px solid #eee, logo '{name}' color {p}, dark links",
            "hero": f"CSS Grid 2 cols: LEFT white bg, {p} text, h1 3.8rem, CTA button; RIGHT background-image url('{hero_url}') cover center",
            "about_media": f"background-image url('{card_url}') cover center, border-radius 12px, border 8px solid white, box-shadow 0 10px 30px rgba(0,0,0,0.05)",
        },
        {
            "name": "Creative Gradient Tech",
            "font": "Poppins",
            "nav":  f"position fixed, background linear-gradient(to right, {p}, {s}), white logo '{name}', white links",
            "hero": f"background linear-gradient(135deg, {p}ee, {s}ee), background-image url('{hero_url}') cover blend-mode multiply, 90vh height, flex-center, white text, h1 5rem font-weight 800",
            "about_media": f"background linear-gradient(45deg, {p}, {s}), border-radius 30px, padding 40px, large white FontAwesome icon matching {btype}",
        },
    ]

    d = DESIGNS[variation_index % 3]
    base_tag = f'<base href="{base_url}">' if base_url else ""

    return (
        "Output ONLY a complete, professional HTML file. Start with <!DOCTYPE html>. End with </html>.\n"
        "Zero markdown. Zero backticks. Zero explanation. No preamble.\n"
        "All CSS inside one <style> tag in <head>.\n"
        f"{base_tag}\n"
        "Use Font Awesome 6.5 CDN and Google Fonts.\n"
        "Images MUST use referrerpolicy=\"no-referrer\" attribute.\n\n"
        f"BUSINESS: {name} in {location}\n"
        f"INDUSTRY: {btype}\n"
        f"COLORS: Primary {p}, Secondary {s}\n"
        f"SERVICES: {', '.join(svc_list)}\n\n"
        f"DESIGN STYLE: {d['name']}\n"
        f"FONT: {d['font']}\n"
        f"NAVBAR: {d['nav']}\n"
        f"HERO: {d['hero']}\n"
        f"ABOUT MEDIA: {d['about_media']}\n\n"
        "MANDATORY SECTIONS (ALL 8):\n"
        "1. Fixed Navbar: logo, 4 links, 'Get Quote' button\n"
        f"2. Hero: full-height background-image url('{hero_url}'), headline about {name}\n"
        "3. Services: 3-column grid with icons for: " + ", ".join(svc_list) + "\n"
        f"4. About: 2-column with image url('{card_url}') and text about {name} in {location}\n"
        "5. Why Choose Us: 4 icon-stat tiles\n"
        "6. Testimonials: 3 review cards with 5-star ratings\n"
        "7. Contact: Name, Email, Phone, Message fields + Submit button\n"
        "8. Footer: Copyright + social icons\n\n"
        f"Write expert marketing copy for a professional {btype} business. NO lorem ipsum.\n"
        "<!DOCTYPE html>"
    )


def _gemini_response_text(resp) -> str:
    if resp is None:
        return ""
    try:
        t = (getattr(resp, "text", None) or "").strip()
        if t:
            return t
    except Exception:
        pass
    chunks: list[str] = []
    for c in getattr(resp, "candidates", None) or []:
        content = getattr(c, "content", None)
        if not content:
            continue
        for p in getattr(content, "parts", None) or []:
            tx = getattr(p, "text", None)
            if tx:
                chunks.append(str(tx))
    return "\n".join(chunks).strip()


def generate_html(data, variation_index, base_url=""):
    global LAST_AI_ERROR, ACTIVE_MODEL
    import time

    if not gemini_client:
        LAST_AI_ERROR = "GEMINI_API_KEY not set. pip install google-genai."
        return None

    # FIX: pass base_url into build_prompt — no longer relies on request context
    prompt = build_prompt(data, variation_index, base_url)

    models_to_try = [ACTIVE_MODEL] + [m for m in GEMINI_MODELS if m != ACTIVE_MODEL]

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                print(f"  [{variation_index}] {model_name} attempt {attempt + 1}...")
                resp = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.82,
                        max_output_tokens=6144,
                        top_p=0.95,
                    ),
                )
                raw = _gemini_response_text(resp)
                if not raw:
                    fb = getattr(resp, "prompt_feedback", None)
                    block = getattr(fb, "block_reason", None) if fb else None
                    LAST_AI_ERROR = f"Empty output (block={block})"
                    time.sleep(1.2 * (attempt + 1))
                    continue

                ACTIVE_MODEL = model_name

                # Robust HTML extraction
                low = raw.lower()
                start_idx = low.find("<!doctype")
                if start_idx == -1:
                    start_idx = low.find("<html")
                end_idx = low.rfind("</html>")

                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    raw = raw[start_idx: end_idx + 7].strip()
                elif "```" in raw:
                    if "```html" in raw:
                        raw = raw.split("```html", 1)[1].split("```", 1)[0].strip()
                    else:
                        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

                if not raw.lower().startswith("<!doctype") and not raw.lower().startswith("<html"):
                    raw = "<!DOCTYPE html>\n" + raw

                if "<meta charset" not in raw.lower() and "<head>" in raw.lower():
                    raw = raw.replace("<head>", '<head>\n<meta charset="UTF-8">', 1)

                if len(raw) < 400:
                    continue

                LAST_AI_ERROR = ""
                print(f"  [{variation_index}] OK — {len(raw):,} chars")
                return raw

            except Exception as me:
                eu = str(me).upper()
                LAST_AI_ERROR = str(me)
                if any(x in eu for x in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                    time.sleep(4)
                    break
                if any(x in eu for x in ["404", "NOT_FOUND"]):
                    break
                if any(x in eu for x in ["503", "OVERLOADED", "UNAVAILABLE"]):
                    time.sleep(2 * (attempt + 1))
                    continue
                time.sleep(1.0 * (attempt + 1))
                continue

    LAST_AI_ERROR = f"All models failed for variation {variation_index}. Last: {LAST_AI_ERROR}"
    return None


def inject_banner(html, site, slug, base_url):
    name = site.get('business_name', 'Your Business')
    btype = site.get('business_type', 'business')
    _, _, emoji, accent = get_category_info(btype)
    dl  = f"{base_url}/download/{slug}"
    wa  = "https://wa.me/447700000000?text=I+want+to+launch+my+AI+website"
    banner = (
        "<style>#_ab{position:fixed;bottom:0;left:0;right:0;z-index:999999;"
        "background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;padding:14px 24px;"
        "display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;"
        "box-shadow:0 -6px 32px rgba(0,0,0,.4);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}"
        "#_ab .l{display:flex;align-items:center;gap:10px}"
        f"#_ab .bg{{background:{accent};color:#fff;padding:3px 10px;border-radius:20px;"
        "font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase}"
        "#_ab .t strong{font-size:15px;display:block}"
        "#_ab .r{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
        "#_ab a,#_ab button{padding:10px 18px;border-radius:30px;font-weight:700;"
        "font-size:13px;cursor:pointer;border:none;text-decoration:none;"
        "display:inline-flex;align-items:center;gap:5px;transition:.2s}"
        "#_ab .g{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}"
        "#_ab .d{background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.2)!important}"
        "#_ab .x{background:transparent;color:rgba(255,255,255,.4);font-size:18px;padding:4px 8px}"
        "body{padding-bottom:78px!important}</style>"
        f'<div id="_ab"><div class="l"><span class="bg">AI Preview</span>'
        f'<div class="t"><strong>{name} — Your website is ready!</strong>'
        f'Free launch with our team</div></div>'
        f'<div class="r"><a href="{wa}" target="_blank" class="g">🚀 Launch Free</a>'
        f'<a href="{dl}" class="d">⬇ Download</a>'
        f'<button class="x" onclick="document.getElementById(\'_ab\').remove();document.body.style.paddingBottom=0">✕</button>'
        f'</div></div>'
    )
    if '<meta charset' not in html.lower():
        html = html.replace('<head>', '<head>\n<meta charset="UTF-8">', 1)
    return html.replace("</body>", f"{banner}\n</body>", 1) if "</body>" in html else html + banner


# ─────────────────────────────────────────────────────────
#  FORM HTML  — FIXED: proper iframe preview scaling
# ─────────────────────────────────────────────────────────

FORM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Build Your Website with AI | Free</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#f0f4ff 0%,#faf5ff 100%);min-height:100vh;padding:40px 20px}
.wrap{max-width:860px;margin:0 auto}
.card{background:rgba(255,255,255,0.85);backdrop-filter:blur(20px);border-radius:32px;box-shadow:0 32px 80px rgba(0,0,0,0.1);border:1px solid rgba(255,255,255,0.5);padding:56px 52px}
h1{font-size:2.2rem;font-weight:800;color:#0f172a;margin-bottom:8px;letter-spacing:-0.5px}
h1 span{background:linear-gradient(135deg,#6e8efb,#a777e3);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{color:#64748b;font-size:1rem;margin-bottom:40px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}
label{display:block;font-size:0.875rem;font-weight:600;color:#374151;margin-bottom:8px}
input,select,textarea{width:100%;padding:14px 18px;border:2px solid #e5e7eb;border-radius:14px;font-size:0.95rem;font-family:'Inter',sans-serif;color:#111;background:rgba(255,255,255,0.8);transition:all 0.3s;outline:none}
input:focus,select:focus,textarea:focus{border-color:#6e8efb;box-shadow:0 0 0 4px rgba(110,142,251,0.15)}
textarea{resize:vertical;min-height:100px}
.color-row{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px}
.color-item{display:flex;flex-direction:column;align-items:center;gap:6px}
.color-item input[type=color]{width:80px;height:44px;border-radius:10px;border:2px solid #e5e7eb;cursor:pointer;padding:3px}
.color-item span{font-size:11px;color:#64748b;font-weight:600}
.btn{width:100%;padding:20px;background:linear-gradient(135deg,#6e8efb,#a777e3,#6e8efb);background-size:200% auto;border:none;border-radius:18px;color:white;font-size:1.05rem;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;cursor:pointer;margin-top:28px;transition:all 0.5s}
.btn:hover{background-position:right center;transform:translateY(-3px);box-shadow:0 20px 40px rgba(110,142,251,0.4)}

/* Loading overlay */
.loading{display:none;position:fixed;inset:0;background:#fff;z-index:9999;flex-direction:column;align-items:center;justify-content:center}
.spinner{width:72px;height:72px;border:4px solid #f0f0f0;border-top:4px solid #6e8efb;border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:28px}
@keyframes spin{to{transform:rotate(360deg)}}
#lt{font-size:1.8rem;font-weight:800;color:#0f172a;margin-bottom:8px}
.prog-wrap{width:100%;max-width:460px;height:8px;background:#f0f0f0;border-radius:99px;overflow:hidden;margin-top:28px}
.prog-fill{height:100%;background:linear-gradient(90deg,#6e8efb,#a777e3);border-radius:99px;transition:width 0.6s ease;width:0%}

/* ── Design selection overlay ── */
.sel-overlay{display:none;position:fixed;inset:0;background:#f0f4ff;z-index:10000;overflow-y:auto;padding:40px 20px 60px}
.sel-header{text-align:center;margin-bottom:36px}
.sel-header h2{font-size:2rem;font-weight:800;color:#0f172a;margin-bottom:6px}
.sel-header p{color:#64748b}

/* Card grid */
.sel-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:32px;max-width:1200px;margin:0 auto}
.d-card{background:white;border-radius:20px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.10);transition:transform 0.25s,box-shadow 0.25s;cursor:pointer}
.d-card:hover{transform:translateY(-6px);box-shadow:0 20px 48px rgba(0,0,0,0.16)}

/* ── THE MAIN FIX: proper iframe scaling ──
   The iframe is 1440px wide × 900px tall (real desktop size).
   We scale it down to fit inside a 340px-wide card preview area.
   Scale factor = 340 / 1440 = ~0.236
   Scaled height = 900 * 0.236 = ~212px  → we add extra to show more of the page
   We actually display at scale 0.30 to show more content:
     - Scaled width  = 1440 * 0.30 = 432px  (overflow:hidden clips it)
     - Scaled height = 900  * 0.30 = 270px  → container height
   We use a wrapper div with overflow:hidden at the exact scaled size. */
.preview-wrap{
  width: 100%;
  height: 270px;
  overflow: hidden;
  position: relative;
  background: #f8f9fa;
}
.preview-wrap iframe{
  width: 1440px;
  height: 900px;
  border: none;
  transform: scale(0.30);
  transform-origin: top left;
  pointer-events: none;
  /* Force the iframe to render at full desktop width regardless of card width */
}

/* Loading placeholder shown while iframe loads */
.preview-loading{
  position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;background:#f8f9ff;
  gap:10px;color:#6e8efb;font-size:0.9rem;font-weight:600;
}
.preview-loading .mini-spin{
  width:36px;height:36px;border:3px solid #e0e7ff;
  border-top-color:#6e8efb;border-radius:50%;
  animation:spin 0.7s linear infinite;
}

.d-info{padding:16px 20px;display:flex;justify-content:space-between;align-items:center;border-top:1px solid #f0f0f0}
.btn-sel{background:linear-gradient(135deg,#6e8efb,#a777e3);color:white;border:none;padding:11px 24px;border-radius:50px;font-weight:700;font-size:0.9rem;cursor:pointer;transition:all 0.2s}
.btn-sel:hover{transform:scale(1.05);box-shadow:0 6px 20px rgba(110,142,251,0.4)}

.error-card{background:#fff5f5;border:2px solid #fecaca;border-radius:12px;padding:20px;text-align:center;color:#dc2626;font-size:0.9rem}

@media(max-width:600px){.card{padding:32px 24px}.row{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<div class="card">
  <h1><span>AI</span> Web Architect</h1>
  <p class="sub">Create a completely custom professional website in minutes — free.</p>
  <form id="aiform">
    <div class="row">
      <div><label>Business Name *</label><input id="bn" placeholder="e.g. Elite Plumbing Solutions" required></div>
      <div><label>Industry *</label>
        <select id="bt" required>
          <option value="" disabled selected>Select your industry</option>
          <option value="plumber">Plumbing &amp; Heating</option>
          <option value="electrician">Electrical Services</option>
          <option value="restaurant">Restaurant / Cafe</option>
          <option value="law">Law Firm / Legal</option>
          <option value="consulting">Business Consulting</option>
          <option value="fitness">Gym / Fitness</option>
          <option value="realestate">Real Estate</option>
          <option value="agency">Digital / Creative Agency</option>
          <option value="shoes">Shoes / Retail</option>
          <option value="beauty">Beauty / Spa</option>
          <option value="medical">Medical / Clinic</option>
          <option value="cleaning">Cleaning Services</option>
          <option value="construction">Construction</option>
          <option value="photography">Photography</option>
          <option value="tech">Technology</option>
          <option value="education">Education</option>
          <option value="other">Other</option>
        </select>
      </div>
    </div>
    <div style="margin-bottom:20px">
      <label>Services (comma separated) *</label>
      <textarea id="sv" placeholder="e.g. Emergency repairs, Boiler installation, Drainage, Gas checks" required></textarea>
    </div>
    <div class="row">
      <div><label>City / Location *</label><input id="loc" placeholder="e.g. Manchester, Lahore, Dubai" required></div>
      <div><label>Preferred Style</label>
        <select id="sty">
          <option value="modern">Modern / Bold</option>
          <option value="professional">Professional / Corporate</option>
          <option value="creative">Creative / Artistic</option>
          <option value="minimal">Minimal / Clean</option>
        </select>
      </div>
    </div>
    <label>Brand Colors</label>
    <div class="color-row">
      <div class="color-item"><input type="color" id="c1" value="#2563eb"><span>Primary</span></div>
      <div class="color-item"><input type="color" id="c2" value="#7c3aed"><span>Secondary</span></div>
      <div class="color-item"><input type="color" id="c3" value="#f8fafc"><span>Background</span></div>
    </div>
    <button type="submit" class="btn">✨ Generate 3 Unique AI Designs →</button>
  </form>
</div>
</div>

<!-- Loading screen -->
<div class="loading" id="ld">
  <div class="spinner"></div>
  <div id="lt">Analysing your business...</div>
  <div style="color:#64748b;font-size:0.95rem;margin-top:6px" id="ls">Building 3 unique designs for you</div>
  <div class="prog-wrap"><div class="prog-fill" id="pf"></div></div>
</div>

<!-- Design selection overlay -->
<div class="sel-overlay" id="so">
  <div class="sel-header">
    <h2>Choose Your Design</h2>
    <p>3 unique AI-generated layouts — click the one you love</p>
  </div>
  <div class="sel-grid" id="sg"></div>
</div>

<script>
const BASE = window.location.origin;
const MSGS = [
  'Analysing your business...',
  'Designing Layout 1 of 3...',
  'Building your homepage sections...',
  'Designing Layout 2 of 3...',
  'Adding colours, fonts and images...',
  'Designing Layout 3 of 3...',
  'Polishing the final details...',
  'Almost ready...'
];

document.getElementById('aiform').addEventListener('submit', async e => {
  e.preventDefault();

  const fd = {
    businessName: document.getElementById('bn').value.trim(),
    businessType: document.getElementById('bt').value,
    services:     document.getElementById('sv').value.trim(),
    location:     document.getElementById('loc').value.trim(),
    style:        document.getElementById('sty').value,
    colors: [
      document.getElementById('c1').value,
      document.getElementById('c2').value,
      document.getElementById('c3').value
    ]
  };

  const ld = document.getElementById('ld');
  const lt = document.getElementById('lt');
  const ls = document.getElementById('ls');
  const pf = document.getElementById('pf');
  ld.style.display = 'flex';

  let mi = 0;
  const ticker = setInterval(() => { mi = (mi + 1) % MSGS.length; lt.textContent = MSGS[mi]; }, 5000);

  const done = () => clearInterval(ticker);
  const fail = msg => {
    done();
    alert('Error: ' + msg);
    ld.style.display = 'none';
  };

  try {
    // Step 1: Register the job
    const r1 = await fetch(`${BASE}/api/generate-site`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fd)
    });
    const d1 = await r1.json();
    if (!d1.success) { fail(d1.message || 'Registration failed'); return; }
    const slug = d1.slug;

    const vars = [];

    // Step 2: Generate each design one at a time
    for (let i = 0; i < 3; i++) {
      lt.textContent = `Generating Design ${i + 1} of 3...`;
      ls.textContent = `AI is writing your full website layout — ~20 seconds`;
      pf.style.width = (10 + i * 25) + '%';

      try {
        const r2 = await fetch(`${BASE}/api/generate-one/${slug}/${i}`);
        const d2 = await r2.json();
        if (d2.success) {
          vars.push({ id: i, url: d2.preview_url });
          pf.style.width = (30 + i * 22) + '%';
        } else {
          console.warn(`Design ${i} failed:`, d2.message);
        }
      } catch (err) {
        console.warn(`Design ${i} network error:`, err);
      }
    }

    done();

    if (vars.length === 0) {
      fail('All 3 designs failed to generate. Check your API key and try again.');
      return;
    }

    pf.style.width = '100%';
    lt.textContent = `${vars.length} Design${vars.length > 1 ? 's' : ''} Ready!`;
    ls.textContent = 'Choose your favourite below...';

    setTimeout(() => {
      ld.style.display = 'none';
      showDesigns(slug, vars);
    }, 600);

  } catch (err) {
    fail(err.message);
  }
});

function showDesigns(slug, vars) {
  const grid = document.getElementById('sg');
  grid.innerHTML = '';

  vars.forEach(v => {
    const card = document.createElement('div');
    card.className = 'd-card';

    // Each card has a preview-wrap with a properly scaled iframe
    card.innerHTML = `
      <div class="preview-wrap" id="wrap-${v.id}">
        <div class="preview-loading" id="pl-${v.id}">
          <div class="mini-spin"></div>
          <span>Loading Design ${v.id + 1}...</span>
        </div>
        <iframe
          id="iframe-${v.id}"
          src="${v.url}"
          scrolling="no"
          referrerpolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin"
          style="opacity:0;transition:opacity 0.4s"
          onload="iframeLoaded(${v.id})"
          onerror="iframeError(${v.id})"
        ></iframe>
      </div>
      <div class="d-info">
        <div>
          <strong style="font-size:0.95rem;color:#0f172a">Design ${v.id + 1}</strong>
          <br><small style="color:#64748b">AI Custom Layout</small>
        </div>
        <button class="btn-sel" onclick="pick('${slug}', ${v.id})">Select This ✓</button>
      </div>`;
    grid.appendChild(card);
  });

  // Show overlay AFTER cards are in DOM
  const overlay = document.getElementById('so');
  overlay.style.display = 'block';
  document.body.style.overflow = 'hidden';

  // Fallback: if iframe hasn't loaded in 15s, show error
  vars.forEach(v => {
    setTimeout(() => {
      const pl = document.getElementById(`pl-${v.id}`);
      const iframe = document.getElementById(`iframe-${v.id}`);
      if (pl && pl.style.display !== 'none' && iframe && iframe.style.opacity === '0') {
        pl.innerHTML = '<div class="error-card">⚠️ Preview timed out — design was generated. Click Select to use it.</div>';
      }
    }, 15000);
  });
}

function iframeLoaded(id) {
  const pl = document.getElementById(`pl-${id}`);
  const iframe = document.getElementById(`iframe-${id}`);
  if (pl) pl.style.display = 'none';
  if (iframe) iframe.style.opacity = '1';
}

function iframeError(id) {
  const pl = document.getElementById(`pl-${id}`);
  if (pl) pl.innerHTML = '<div class="error-card">⚠️ Preview unavailable — design was still generated. Click Select to use it.</div>';
}

async function pick(slug, idx) {
  document.getElementById('so').style.display = 'none';
  document.body.style.overflow = 'auto';

  const ld = document.getElementById('ld');
  const lt = document.getElementById('lt');
  const pf = document.getElementById('pf');
  ld.style.display = 'flex';
  lt.textContent = 'Finalising your website...';
  pf.style.width = '60%';

  try {
    const r = await fetch(`${BASE}/api/select-design`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug, designIndex: idx })
    });
    const d = await r.json();
    pf.style.width = '100%';
    if (d.success) {
      window.location.href = d.previewUrl;
    } else {
      alert('Error: ' + (d.message || 'Unknown error'));
      ld.style.display = 'none';
      document.getElementById('so').style.display = 'block';
      document.body.style.overflow = 'hidden';
    }
  } catch (e) {
    alert('Error: ' + e.message);
    ld.style.display = 'none';
    document.getElementById('so').style.display = 'block';
    document.body.style.overflow = 'hidden';
  }
}
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────

def html_r(body, status=200):
    resp = Response(body.encode('utf-8'), status=status, mimetype='text/html; charset=utf-8')
    return resp

@app.route('/')
def home():
    return html_r(FORM_HTML)

@app.route('/build-with-ai')
def build_page():
    return html_r(FORM_HTML)

def _health_payload():
    return {
        "status": "ok",
        "gemini": bool(gemini_client),
        "active_model": ACTIVE_MODEL,
        "last_error": LAST_AI_ERROR or "none",
        "db": bool(DATABASE_URL),
    }

@app.route('/health')
def health():
    return jsonify(_health_payload())

@app.route('/api/health', methods=['GET', 'HEAD', 'OPTIONS'])
def api_health():
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify(_health_payload())

@app.route('/api/debug')
def debug():
    return jsonify({
        "GEMINI_KEY_set": bool(GEMINI_KEY),
        "gemini_ready":   bool(gemini_client),
        "active_model":   ACTIVE_MODEL,
        "last_error":     LAST_AI_ERROR or "none",
    })

@app.route('/api/list-models')
def list_models():
    if not gemini_client:
        return jsonify({"error": "Gemini not initialised"})
    try:
        names = [str(m.name) for m in gemini_client.models.list()]
        return jsonify({"models": names, "active": ACTIVE_MODEL})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/generate-site', methods=['POST', 'OPTIONS'])
def start_generation():
    if request.method == 'OPTIONS':
        return '', 204
    if not DATABASE_URL:
        return jsonify({
            "success": False,
            "message": "DATABASE_URL is not set. Add it in Vercel → Settings → Environment Variables.",
        }), 503
    try:
        data = request.get_json()
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "businessName is required"}), 400
        slug = re.sub(r'[^a-z0-9]+', '-', data['businessName'].lower().strip())
        slug = f"{slug}-{random.randint(10000, 99999)}"
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO sites (slug,business_name,business_type,location,services,style,colors,status,message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'STARTING','Ready')
            ON CONFLICT (slug) DO NOTHING
        """, (slug, data.get('businessName'), data.get('businessType', 'other'),
              data.get('location', ''), data.get('services', ''),
              data.get('style', 'modern'), data.get('colors', [])))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True, "slug": slug})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/generate-one/<slug>/<int:idx>', methods=['GET', 'HEAD', 'OPTIONS'])
def generate_one(slug, idx):
    if request.method == 'OPTIONS':
        return '', 204
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

        # FIX: pass base_url explicitly so build_prompt() doesn't rely on request context internally
        base_url = request.host_url.rstrip('/')
        html = generate_html(dict(site), idx, base_url=base_url)

        if not html:
            return jsonify({"success": False, "message": LAST_AI_ERROR or "Generation failed"})

        conn2 = get_db()
        cur2  = conn2.cursor()
        cur2.execute("DELETE FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        cur2.execute("INSERT INTO variations (site_slug,variation_index,html_content) VALUES (%s,%s,%s)",
                     (slug, idx, html))
        status = 'AWAITING_SELECTION' if idx == 2 else f'DONE_{idx}'
        cur2.execute("UPDATE sites SET status=%s WHERE slug=%s", (status, slug))
        conn2.commit()
        cur2.close(); conn2.close()

        return jsonify({
            "success":      True,
            "variation_id": idx,
            "preview_url":  f"{base_url}/view-design/{slug}/{idx}",
            "all_done":     idx == 2,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/select-design', methods=['POST', 'OPTIONS'])
def select_design():
    if request.method == 'OPTIONS':
        return '', 204
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
        cur.execute("""INSERT INTO final_sites (site_slug,html_content)
            VALUES (%s,%s) ON CONFLICT (site_slug) DO UPDATE SET html_content=EXCLUDED.html_content""",
            (slug, row['html_content']))
        cur.execute("UPDATE sites SET status='COMPLETED' WHERE slug=%s", (slug,))
        conn.commit()
        cur.close(); conn.close()
        base = request.host_url.rstrip('/')
        return jsonify({"success": True, "previewUrl": f"{base}/s/{slug}", "downloadUrl": f"{base}/download/{slug}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    """Return raw generated HTML for preview inside iframe — NO banner."""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        row = cur.fetchone()
        conn.close()
        if not row:
            return html_r("<h1 style='font-family:sans-serif;padding:40px;color:#dc2626'>Design not found</h1>", 404)
        return html_r(row[0])
    except Exception as e:
        return html_r(f"<h1 style='font-family:sans-serif;padding:40px;color:#dc2626'>DB Error: {e}</h1>", 500)

@app.route('/s/<slug>')
def show_site(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if row:
            return html_r(row[0])
        return html_r("<h1 style='font-family:sans-serif;padding:40px'>Site not found</h1>", 404)
    except Exception as e:
        return html_r(f"<h1 style='font-family:sans-serif;padding:40px;color:red'>Error: {e}</h1>", 500)

@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return html_r("<h1>Not found</h1>", 404)
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0].encode('utf-8'))
        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f"{slug}_website.zip")
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

@app.route('/api/submit-template', methods=['POST', 'OPTIONS'])
def submit_template():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "message": "No file part"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "message": "No selected file"}), 400
        if file and file.filename.lower().endswith('.zip'):
            name          = request.form.get('name')
            email         = request.form.get('email')
            template_name = request.form.get('template_name')
            category      = request.form.get('category')
            preview_url   = request.form.get('preview_url')
            description   = request.form.get('description')
            if not template_name or not name or not email:
                return jsonify({"success": False, "message": "Missing required fields"}), 400
            import time
            timestamp = int(time.time())
            filename  = secure_filename(f"{timestamp}_{secure_filename(template_name)}_{file.filename}")
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO template_submissions (name,email,template_name,category,preview_url,file_path,description)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (name, email, template_name, category, preview_url, file_path, description))
            conn.commit()
            cur.close(); conn.close()
            return jsonify({"success": True, "message": "Template submitted successfully!"})
        else:
            return jsonify({"success": False, "message": "Only .zip files are allowed"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
