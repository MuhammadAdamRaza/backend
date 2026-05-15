import os
import json
import re
import random
import traceback
from html import escape as html_escape
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
# Wide CORS: Live Server, localhost, production HTML on other hosts, and null/file origins when allowed by browser.
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
    """Ensure every response carries CORS headers and no iframe-blocking headers."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept"
    response.headers["Access-Control-Max-Age"] = "86400"
    # Remove ALL framing restrictions so iframes work from any origin (including file://).
    response.headers.pop("X-Frame-Options", None)
    # Strip frame-ancestors from CSP — file:// is not a network scheme so '*' blocks it.
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
    resp.headers.setdefault(
        "Access-Control-Allow-Methods",
        "GET, HEAD, POST, PUT, DELETE, OPTIONS, PATCH",
    )
    resp.headers.setdefault(
        "Access-Control-Allow-Headers",
        "Content-Type, Authorization, X-Requested-With, Accept",
    )
    return resp


@app.errorhandler(Exception)
def _handle_any_exception(exc):
    """Uncaught errors skip @app.after_request; without CORS the browser reports a misleading CORS failure."""
    if isinstance(exc, HTTPException):
        resp = exc.get_response()
        return _corsify(resp)
    traceback.print_exc()
    safe = str(exc) if app.debug else "Server error — see Vercel function logs for details."
    r = jsonify({"success": False, "message": safe})
    r.status_code = 500
    return _corsify(r)


# Vercel serverless filesystem is read-only except /tmp — avoid crashing on import.
_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if _SERVERLESS:
    UPLOAD_FOLDER = os.path.join("/tmp", "awake_uploads", "templates")
else:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "templates")
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

# ────────────────────────────────────────────────
#  CATEGORY IMAGES  (curated Unsplash IDs)
# ────────────────────────────────────────────────

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

# ────────────────────────────────────────────────
#  DATABASE
# ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    """Connect to Postgres. The Neon URL already contains sslmode and channel_binding;
    psycopg2 must NOT receive them as extra kwargs — doing so raises a conflict error."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    # psycopg2 parses the full DSN including sslmode from the URL — no extra kwargs needed.
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
        # Add unique constraint safely
        cur.execute("""
            DO $$ BEGIN
                -- Clean up any existing duplicates before adding constraint
                DELETE FROM variations a USING variations b
                WHERE a.id < b.id 
                AND a.site_slug = b.site_slug 
                AND a.variation_index = b.variation_index;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'variations_slug_idx_key'
                ) THEN
                    ALTER TABLE variations ADD CONSTRAINT variations_slug_idx_key UNIQUE (site_slug, variation_index);
                END IF;
            END$$;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS template_submissions (
                id SERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                template_name TEXT,
                category TEXT,
                preview_url TEXT,
                file_path TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
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


# ────────────────────────────────────────────────
#  GEMINI AI  (only — no OpenAI)
# ────────────────────────────────────────────────

GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY") or
    os.getenv("GOOGLE_API_KEY") or
    os.getenv("GOOGLE_GEMINI_KEY") or ""
)

# Short IDs work with google-genai; order is fastest / most available first.
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
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
    print("WARNING: GEMINI_API_KEY not set in environment variables")

# ────────────────────────────────────────────────
#  PREMIUM TEMPLATES (static HTML — no AI / Gemini)
# ────────────────────────────────────────────────

import re
from html import escape as _e

INDUSTRY = {
    "plumber": {"label": "Plumbing & Heating", "hero": "https://images.unsplash.com/photo-1607472586893-edb57bdc0e39?w=1200&q=80", "team": "https://images.unsplash.com/photo-1581578731548-c64695cc6952?w=800&q=80", "work": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=800&q=80", "pitch": "Gas-safe minded engineers with fast call-outs, transparent quotes, and workmanship you can trust across every job."},
    "electrician": {"label": "Electrical Services", "hero": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1200&q=80", "team": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=800&q=80", "work": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80", "pitch": "Qualified electricians for domestic and commercial installs, fault finding, rewires, and safety certificates."},
    "restaurant": {"label": "Restaurant & Café", "hero": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1200&q=80", "team": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&q=80", "work": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=800&q=80", "pitch": "Seasonal menus, warm hospitality, and memorable dining in the heart of the community."},
    "law": {"label": "Legal Services", "hero": "https://images.unsplash.com/photo-1589829545855-d10d557cf57f?w=1200&q=80", "team": "https://images.unsplash.com/photo-1560250097-0b93528c311a?w=800&q=80", "work": "https://images.unsplash.com/photo-1450101499163-c8848c66ca85?w=800&q=80", "pitch": "Clear advice, disciplined case management, and outcomes-focused representation."},
    "consulting": {"label": "Business Consulting", "hero": "https://images.unsplash.com/photo-1552664730-d307ca884978?w=1200&q=80", "team": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80", "work": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=800&q=80", "pitch": "Strategy, operations, and growth programmes tailored to ambitious UK small businesses."},
    "fitness": {"label": "Gym & Fitness", "hero": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=1200&q=80", "team": "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?w=800&q=80", "work": "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?w=800&q=80", "pitch": "Expert coaching, modern equipment, and programmes built for sustainable results."},
    "realestate": {"label": "Real Estate", "hero": "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=1200&q=80", "team": "https://images.unsplash.com/photo-1560472354-b33ff0c44a43?w=800&q=80", "work": "https://images.unsplash.com/photo-1560185127-6ed189bf02f4?w=800&q=80", "pitch": "Local market insight, honest valuations, and a smooth journey from viewing to completion."},
    "agency": {"label": "Creative Agency", "hero": "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1200&q=80", "team": "https://images.unsplash.com/photo-1529333166437-7750a6dd4a70?w=800&q=80", "work": "https://images.unsplash.com/photo-1552664730-d307ca884978?w=800&q=80", "pitch": "Brand, web, and campaigns that help UK businesses stand out and convert more customers online."},
    "other": {"label": "Professional Services", "hero": "https://images.unsplash.com/photo-1497366754035-f200968a6e72?w=1200&q=80", "team": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80", "work": "https://images.unsplash.com/photo-1556761175-b413da4baf72?w=800&q=80", "pitch": "Dependable expertise, transparent communication, and solutions designed around your goals."},
}

SVC_BLURB = [
    "A complete service delivered by qualified specialists — we confirm scope in writing before work begins so you know exactly what to expect.",
    "Popular with homeowners and businesses across {location} — flexible scheduling including urgent appointments when you need us most.",
    "Includes a full consultation, plain-English summary of options, and follow-up support after the job is signed off.",
    "Completed to recognised UK standards with certificates, photos, and documentation supplied on request.",
    "Ideal for planned maintenance and reactive call-outs — we prioritise safety, cleanliness, and respect for your property.",
    "Backed by our satisfaction promise and a friendly team who explain every step without jargon or pressure.",
]

FEATURES = [
    ("bi-lightning-charge", "Rapid response", "Same-day and emergency slots where possible — we respect your time and communicate arrival windows clearly."),
    ("bi-shield-check", "Fully insured", "Comprehensive cover and qualified staff — peace of mind for domestic and commercial clients alike."),
    ("bi-cash-coin", "Transparent pricing", "Written quotes before work starts — no hidden extras or surprise charges on the day."),
    ("bi-chat-dots", "Clear communication", "Updates by phone or email throughout — you always know what happens next."),
    ("bi-award", "Proven quality", "Hundreds of completed projects in {location} — ask for local references anytime."),
    ("bi-headset", "Aftercare support", "We check in after completion to ensure you are completely satisfied with the result."),
]

TESTIMONIALS = [
    ("James Mitchell", "Homeowner, {location}", "From first call to finish, the team was punctual, tidy, and transparent on price. I have already recommended them to neighbours."),
    ("Priya Sharma", "Business owner", "They understood our deadlines and delivered exactly what was promised. Communication was excellent throughout the project."),
    ("David Hughes", "Property manager", "Professional paperwork, reliable scheduling, and quality work across multiple sites — exactly what we need."),
    ("Sarah Clarke", "Local resident", "Honest advice, no upselling, and a finish we are proud to show visitors. Genuinely the best experience we have had."),
]

TEAM = [
    ("Alex Turner", "Director"),
    ("Jordan Lee", "Lead technician"),
    ("Sam Patel", "Customer success"),
    ("Riley Morgan", "Operations"),
]

BLOG = [
    ("How to choose the right {label_l} provider in {location}", "A practical checklist for comparing quotes, credentials, and reviews before you commit."),
    ("5 questions to ask before booking {label_l} work", "Protect your budget and timeline with these expert-approved questions."),
    ("Why {name} invests in ongoing training", "How our team stays current with regulations, tools, and customer care standards."),
]

AWARDS = ["Fully insured", "DBS checked", "UK standards", "5★ rated", "Written quotes", "Local team"]


def _parse_services(raw):
    if isinstance(raw, list):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = [s.strip() for s in str(raw or "").split(",") if s.strip()]
    if not items:
        items = ["Free consultation", "Professional installation", "Maintenance & support"]
    while len(items) < 3:
        items.append(items[-1])
    return items[:8]


def _parse_colors(raw):
    if isinstance(raw, list) and len(raw) >= 2:
        return str(raw[0] or "#2563eb").strip(), str(raw[1] or "#7c3aed").strip(), str(raw[2] if len(raw) > 2 else "#f8fafc").strip()
    return "#2563eb", "#7c3aed", "#f8fafc"


def _theme(vi, primary, secondary, surface):
    if vi == 0:
        return {"bg": "#0b1220", "text": "#f1f5f9", "card": "#151f32", "muted": "#94a3b8", "alt": "#1e293b", "hero_style": "dark"}
    if vi == 1:
        return {"bg": surface, "text": "#0f172a", "card": "#ffffff", "muted": "#64748b", "alt": "#f1f5f9", "hero_style": "light"}
    return {"bg": "#1a1033", "text": "#faf5ff", "card": "#261b45", "muted": "#c4b5fd", "alt": "#2d1f4e", "hero_style": "bold"}


def build_premium_html(data, variation_index):
    name_raw = data.get("businessName") or data.get("business_name") or "Your Business"
    name = _e(name_raw)
    btype = (data.get("businessType") or data.get("business_type") or "other").lower()
    loc = _e(data.get("location") or "the UK")
    style = (data.get("style") or "modern").lower()
    ind = INDUSTRY.get(btype, INDUSTRY["other"])
    label = _e(ind["label"])
    label_l = label.lower()
    svcs = [_e(s) for s in _parse_services(data.get("services"))]
    primary, secondary, surface = _parse_colors(data.get("colors"))
    vi = int(variation_index) % 3
    t = _theme(vi, primary, secondary, surface)
    bg, text, card, muted, alt = t["bg"], t["text"], t["card"], t["muted"], t["alt"]
    pitch = _e(ind["pitch"])
    hero_img, team_img, work_img = ind["hero"], ind["team"], ind["work"]
    email_slug = re.sub(r"[^a-z0-9]", "", name_raw.lower()) or "hello"

    headlines = {
        "modern": [f"The smarter way to book {label_l} in {loc}", f"{name} — modern {label_l} for {loc}", f"Meet the future of {label_l} in {loc}"],
        "professional": [f"Trusted {label_l} specialists serving {loc}", f"{name} — professional {label_l} you can rely on", f"Expert {label_l} for homes and businesses in {loc}"],
        "creative": [f"Bold {label_l} that stands out in {loc}", f"{name} reimagines {label_l} in {loc}", f"Creative solutions for {label_l} in {loc}"],
        "minimal": [f"Simple, honest {label_l} in {loc}", f"{name} — clear {label_l}, done right", f"Focused {label_l} for {loc}"],
    }
    hlist = headlines.get(style, headlines["modern"])
    headline = hlist[vi]
    overlay = f"linear-gradient(135deg,{primary}dd 0%,{secondary}bb 50%,{bg}ee 100%)"
    font_heading = "Plus Jakarta Sans" if vi != 2 else "Outfit"

    # Services grid (detailed)
    svc_icons = ["bi-wrench", "bi-tools", "bi-gear-wide-connected", "bi-house-check", "bi-clipboard-check", "bi-truck", "bi-star", "bi-heart-pulse"]
    svc_rows = []
    for i, svc in enumerate(svcs):
        blurb = SVC_BLURB[i % len(SVC_BLURB)].format(location=loc)
        svc_rows.append(
            f'<div class="col-md-6 col-xl-4"><div class="box h-100">'
            f'<div class="icon-pill"><i class="bi {svc_icons[i % len(svc_icons)]}"></i></div>'
            f"<h3 class=\"h4 fw-bold mb-3\">{svc}</h3>"
            f'<p class="mb-0 muted">{_e(blurb)}</p></div></div>'
        )
    services_html = "".join(svc_rows)

    feat_rows = []
    for icon, title, desc in FEATURES[:6]:
        feat_rows.append(
            f'<div class="col-md-6 col-lg-4"><div class="box h-100">'
            f'<div class="icon-pill"><i class="bi {icon}"></i></div>'
            f'<h3 class="h5 fw-bold">{_e(title)}</h3>'
            f'<p class="muted mb-0">{_e(desc.format(location=loc))}</p></div></div>'
        )
    features_html = "".join(feat_rows)

    testi = []
    for person, role, quote in TESTIMONIALS:
        testi.append(
            f'<div class="col-md-6 col-lg-3"><div class="box h-100">'
            f'<div class="text-warning mb-2">★★★★★</div>'
            f'<p class="mb-3">"{_e(quote.format(location=loc))}"</p>'
            f'<div class="d-flex gap-2 align-items-center">'
            f'<div class="av">{_e(person[0])}</div><div><strong class="small">{_e(person)}</strong><br>'
            f'<span class="small muted">{_e(role.format(location=loc))}</span></div></div></div></div>'
        )
    testi_html = "".join(testi)

    prices = []
    for tier, price, desc, feats, star in [
        ("Starter", "From £99", "Straightforward jobs and quick advice.", ["Site visit", "Written estimate", "Standard warranty"], False),
        ("Professional", "From £249", "Our most popular package for complete peace of mind.", ["Priority scheduling", "Premium materials", "12-month phone support"], True),
        ("Enterprise", "Custom quote", "Larger projects and commercial contracts.", ["Dedicated manager", "Flexible billing", "Planned maintenance"], False),
    ]:
        lis = "".join(f'<li><i class="bi bi-check2-circle me-2"></i>{_e(f)}</li>' for f in feats)
        cls = " box featured" if star else " box"
        prices.append(
            f'<div class="col-lg-4"><div class="{cls.strip()}">'
            f'<p class="fw-bold text-uppercase small accent">{_e(tier)}</p>'
            f'<h3 class="display-6 fw-bold">{_e(price)}</h3>'
            f'<p class="muted">{_e(desc)}</p><ul class="list-unstyled mb-4">{lis}</ul>'
            f'<a href="#contact" class="btn-main w-100 text-center d-block">Get a quote</a></div></div>'
        )
    pricing_html = "".join(prices)

    faqs = [
        (f"How quickly can you help in {loc}?", "Most enquiries receive a reply within 2 hours. Emergency and same-day slots are often available — call us for live availability."),
        ("Are quotes free and without obligation?", "Yes. We provide clear written estimates before any work begins so you can decide with confidence."),
        (f"Which areas do you cover?", f"We serve {loc} and surrounding postcodes. Send your address and we will confirm coverage immediately."),
        (f"What makes {name} different?", "Transparent pricing, qualified staff, tidy workmanship, and communication in plain English from start to finish."),
        ("How do I pay?", "Bank transfer, card, and invoice options for trade clients. Payment terms are explained on every quote."),
        ("Do you offer guarantees?", "Yes — workmanship guarantees are included on eligible services and documented in your quote."),
    ]
    faq_html = ""
    for i, (q, a) in enumerate(faqs):
        faq_html += (
            f'<div class="accordion-item acc-item">'
            f'<h2 class="accordion-header"><button class="accordion-button collapsed" type="button" '
            f'data-bs-toggle="collapse" data-bs-target="#fq{vi}{i}">{q}</button></h2>'
            f'<div id="fq{vi}{i}" class="accordion-collapse collapse" data-bs-parent="#faqAcc{vi}">'
            f'<div class="accordion-body muted">{_e(a)}</div></div></div>'
        )

    blog_cards = ""
    for title_tpl, excerpt in BLOG:
        blog_cards += (
            f'<div class="col-md-4"><div class="box h-100">'
            f'<div class="blog-thumb" style="background-image:url({work_img})"></div>'
            f'<div class="p-4"><h3 class="h5 fw-bold">{_e(title_tpl.format(label_l=label_l, location=loc, name=name))}</h3>'
            f'<p class="muted small">{_e(excerpt.format(label_l=label_l, name=name))}</p>'
            f'<a href="#" class="accent fw-semibold">Read more →</a></div></div></div>'
        )

    team_html = ""
    for person, role in TEAM:
        team_html += (
            f'<div class="col-6 col-md-3"><div class="box text-center h-100">'
            f'<div class="av mx-auto mb-3">{_e(person[0])}</div>'
            f'<h3 class="h6 fw-bold mb-1">{_e(person)}</h3><p class="small muted mb-0">{_e(role)}</p></div></div>'
        )

    logos = "".join(f'<span class="logo-pill">{_e(a)}</span>' for a in AWARDS)
    nav_extra = "rounded-pill px-4" if vi == 1 else ""

    # Layout accents per design
    hero_class = "hero hero-a" if vi == 0 else ("hero hero-b" if vi == 1 else "hero hero-c")
    section_alt = f"background:{alt};"

    return f"""<!DOCTYPE html>
<html lang="en-GB" class="theme-{vi}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} | {label} — {loc}</title>
<meta name="description" content="{name} — {pitch} Serving {loc}.">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--p:{primary};--s:{secondary};--bg:{bg};--text:{text};--card:{card};--muted:{muted};--alt:{alt}}}
*{{box-sizing:border-box}}
body{{font-family:'{font_heading}',system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;line-height:1.65}}
.theme-0 .accent,.theme-2 .accent{{color:var(--p)}}
.theme-1 .accent{{color:var(--p)}}
.muted{{color:var(--muted)}}
.nav-wrap{{backdrop-filter:blur(12px);background:color-mix(in srgb,var(--bg) 90%,transparent);border-bottom:1px solid rgba(128,128,128,.12);position:sticky;top:0;z-index:1000}}
.nav-wrap .nav-link{{color:var(--text);font-weight:600;font-size:.95rem}}
.sec{{padding:clamp(64px,8vw,100px) 0}}
.box{{background:var(--card);border-radius:20px;padding:clamp(24px,3vw,36px);border:1px solid rgba(128,128,128,.12);height:100%;transition:transform .25s,box-shadow .25s}}
.box:hover{{transform:translateY(-4px);box-shadow:0 20px 50px rgba(0,0,0,.12)}}
.box.featured{{border:2px solid var(--p);box-shadow:0 12px 40px color-mix(in srgb,var(--p) 25%,transparent)}}
.icon-pill{{width:52px;height:52px;border-radius:14px;background:var(--p);color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.25rem;margin-bottom:18px}}
.btn-main{{background:var(--p);color:#fff!important;padding:14px 32px;border-radius:12px;font-weight:700;text-decoration:none;display:inline-block;border:none}}
.btn-ghost{{border:2px solid var(--p);color:var(--p)!important;padding:12px 28px;border-radius:12px;font-weight:700;text-decoration:none;background:transparent}}
.hero{{position:relative;min-height:min(92vh,900px);display:flex;align-items:center;overflow:hidden}}
.hero-img{{position:absolute;inset:0;background:center/cover no-repeat}}
.hero-mask{{position:absolute;inset:0;background:{overlay}}}
.hero-inner{{position:relative;z-index:2}}
.hero-b .hero-inner{{text-align:center}}
.hero-c .hero-inner h1{{font-size:clamp(2.2rem,5vw,3.5rem)}}
.stat-big{{font-size:clamp(2rem,4vw,3rem);font-weight:800;color:var(--p);line-height:1}}
.av{{width:48px;height:48px;border-radius:50%;background:var(--p);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;flex-shrink:0}}
.logo-pill{{display:inline-block;padding:10px 18px;border-radius:10px;background:var(--card);margin:6px;font-weight:600;font-size:.85rem;border:1px solid rgba(128,128,128,.1)}}
.cta-strip{{background:linear-gradient(135deg,var(--p),var(--s));color:#fff;border-radius:24px;padding:clamp(40px,6vw,72px)}}
.blog-thumb{{height:140px;background-size:cover;background-position:center;border-radius:16px 16px 0 0;margin:-36px -36px 20px -36px}}
.acc-item{{background:transparent!important;border-color:rgba(128,128,128,.15)!important}}
.acc-item .accordion-button{{background:transparent!important;color:var(--text)!important;box-shadow:none!important;font-weight:600}}
.problem-grid .stat-big{{font-size:2.5rem}}
.map-placeholder{{min-height:280px;border-radius:20px;background:var(--alt) center/cover url('https://images.unsplash.com/photo-1524661135-423995f22d0b?w=800&q=60');border:1px solid rgba(128,128,128,.15)}}
.footer-grid a{{color:var(--muted);text-decoration:none}}
.footer-grid a:hover{{color:var(--p)}}
.badge-top{{background:color-mix(in srgb,var(--p) 22%,transparent);border:1px solid color-mix(in srgb,var(--p) 40%,transparent);padding:8px 16px;border-radius:999px;font-weight:600;font-size:.9rem}}
</style>
</head>
<body>
<header class="nav-wrap">
<nav class="navbar navbar-expand-lg py-3">
<div class="container">
<a class="navbar-brand fw-bold fs-4" href="#" style="color:var(--text)">{name}</a>
<button class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#mainNav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="mainNav">
<ul class="navbar-nav ms-auto align-items-lg-center gap-lg-1">
<li class="nav-item"><a class="nav-link" href="#services">Services</a></li>
<li class="nav-item"><a class="nav-link" href="#how">How it works</a></li>
<li class="nav-item"><a class="nav-link" href="#reviews">Reviews</a></li>
<li class="nav-item"><a class="nav-link" href="#pricing">Pricing</a></li>
<li class="nav-item"><a class="nav-link" href="#faq">FAQ</a></li>
<li class="nav-item"><a class="btn-main ms-lg-2 {nav_extra}" href="#contact">Free quote</a></li>
</ul></div></div></nav>
</header>

<!-- 1 Hero -->
<section class="{hero_class}" id="top">
<div class="hero-img" style="background-image:url('{hero_img}')"></div>
<div class="hero-mask"></div>
<div class="container hero-inner">
<div class="row align-items-center g-5">
<div class="col-lg-7">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> Serving {loc} &amp; nearby</span>
<h1 class="display-3 fw-bold mb-4 lh-sm">{headline}</h1>
<p class="lead mb-4" style="max-width:38rem">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4">
<a href="#contact" class="btn-main btn-lg">Book free consultation</a>
<a href="#services" class="btn-ghost btn-lg">View all services</a>
</div>
<p class="small muted">Trusted locally · Clear written quotes · Qualified team · 5★ reviews</p>
</div>
<div class="col-lg-5 {'d-none d-lg-block' if vi != 1 else ''}">
<img src="{hero_img}" alt="{name}" class="img-fluid rounded-4 shadow-lg" style="max-height:440px;width:100%;object-fit:cover">
</div></div></div></section>

<!-- 2 Logo cloud -->
<section class="sec pt-0"><div class="container text-center">
<p class="text-uppercase fw-bold small muted mb-3">Trusted by homeowners &amp; businesses</p>
<div>{logos}</div></div></section>

<!-- 3 Problem -->
<section class="sec problem-grid" style="{section_alt}">
<div class="container">
<div class="row g-5 align-items-center">
<div class="col-lg-6">
<p class="text-uppercase fw-bold small accent mb-2">The challenge</p>
<h2 class="display-5 fw-bold mb-4">The cost of choosing the wrong {label_l} provider</h2>
<p class="fs-5 muted">Too many people in {loc} face delayed call-outs, vague quotes, and messy workmanship. That costs time, money, and peace of mind.</p>
<ul class="list-unstyled fs-5">
<li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Hidden fees added on the day</li>
<li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Poor communication and no-shows</li>
<li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Work that fails inspection or needs redoing</li>
</ul></div>
<div class="col-lg-6">
<div class="row g-3 text-center">
<div class="col-6"><div class="box"><div class="stat-big">38%</div><p class="muted small mb-0">Report bad experiences</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">£240</div><p class="muted small mb-0">Avg. cost of fixes</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">3 days</div><p class="muted small mb-0">Typical wait elsewhere</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">24/7</div><p class="muted small mb-0">We answer emergencies</p></div></div>
</div></div></div></div></section>

<!-- 4 Solution -->
<section class="sec">
<div class="container">
<div class="row g-5 align-items-center">
<div class="col-lg-6 order-lg-2">
<img src="{work_img}" class="img-fluid rounded-4 shadow" alt="Our work">
</div>
<div class="col-lg-6 order-lg-1">
<p class="text-uppercase fw-bold small accent mb-2">The solution</p>
<h2 class="display-5 fw-bold mb-4">Meet the future of {label_l} in {loc}</h2>
<p class="fs-5 muted mb-4">{name} combines qualified people, modern tools, and a customer-first process — so you get reliable results without the stress.</p>
<p class="muted">From the first phone call to final sign-off, you always know who is coming, what it costs, and when it will be done.</p>
</div></div></div></section>

<!-- 5 Mission -->
<section class="sec" style="{section_alt}">
<div class="container">
<div class="row justify-content-center text-center">
<div class="col-lg-8">
<p class="text-uppercase fw-bold small accent mb-2">Why we build</p>
<h2 class="display-5 fw-bold mb-4">Our mission</h2>
<p class="fs-5 muted">We believe every client in {loc} deserves {label_l} that is honest, fairly priced, and finished to a standard we would accept in our own homes. That is why {name} exists — to raise the bar for local service businesses.</p>
</div></div></div></section>

<!-- 6 Core features -->
<section class="sec" id="features">
<div class="container">
<div class="text-center mb-5 mx-auto" style="max-width:720px">
<p class="text-uppercase fw-bold small accent mb-2">Capabilities</p>
<h2 class="display-5 fw-bold mb-3">Everything you need, nothing you do not</h2>
<p class="muted">Six reasons clients choose {name} for {label_l} across {loc}.</p>
</div>
<div class="row g-4">{features_html}</div></div></section>

<!-- 7 Our services (form input) -->
<section class="sec" id="services" style="{section_alt}">
<div class="container">
<div class="text-center mb-5 mx-auto" style="max-width:760px">
<p class="text-uppercase fw-bold small accent mb-2">Our services</p>
<h2 class="display-5 fw-bold mb-3">Comprehensive {label_l} in {loc}</h2>
<p class="muted fs-5">Every service below is delivered by our in-house team — tailored to your property, budget, and timeline. These are the specialties you asked for when you started your project with us.</p>
</div>
<div class="row g-4">{services_html}</div></div></section>

<!-- 8 How it works -->
<section class="sec" id="how">
<div class="container">
<div class="text-center mb-5">
<h2 class="display-5 fw-bold">How it works — setup in 3 simple steps</h2>
<p class="muted">A clear process from enquiry to completion.</p>
</div>
<div class="row g-4">
<div class="col-md-4"><div class="box text-center h-100">
<div class="display-3 fw-bold accent opacity-50 mb-2">01</div>
<h3 class="h4 fw-bold">Tell us what you need</h3>
<p class="muted mb-0">Call, email, or use the form below. We ask the right questions so our visit is productive.</p>
</div></div>
<div class="col-md-4"><div class="box text-center h-100">
<div class="display-3 fw-bold accent opacity-50 mb-2">02</div>
<h3 class="h4 fw-bold">Receive a clear plan</h3>
<p class="muted mb-0">Written options, timeline, and pricing — no jargon, no pressure, no day-of surprises.</p>
</div></div>
<div class="col-md-4"><div class="box text-center h-100">
<div class="display-3 fw-bold accent opacity-50 mb-2">03</div>
<h3 class="h4 fw-bold">We deliver &amp; follow up</h3>
<p class="muted mb-0">Quality work, tidy finish, and a check-in afterwards to ensure you are completely happy.</p>
</div></div>
</div></div></section>

<!-- 9 Stats -->
<section class="sec pt-0" style="{section_alt}">
<div class="container"><div class="row g-4 text-center">
<div class="col-6 col-md-3"><div class="box"><div class="stat-big">15+</div><p class="muted mb-0">Years combined experience</p></div></div>
<div class="col-6 col-md-3"><div class="box"><div class="stat-big">2,400+</div><p class="muted mb-0">Projects completed</p></div></div>
<div class="col-6 col-md-3"><div class="box"><div class="stat-big">98%</div><p class="muted mb-0">Would recommend us</p></div></div>
<div class="col-6 col-md-3"><div class="box"><div class="stat-big">4.9</div><p class="muted mb-0">Average review score</p></div></div>
</div></div></section>

<!-- 10 Case study / ROI -->
<section class="sec">
<div class="container">
<div class="row g-5 align-items-center">
<div class="col-lg-6">
<p class="text-uppercase fw-bold small accent mb-2">Results</p>
<h2 class="display-5 fw-bold mb-4">Real data. Real growth.</h2>
<p class="muted fs-5">A recent commercial client in {loc} reduced repeat call-outs by 40% after switching to our planned maintenance programme — saving time and budget every quarter.</p>
</div>
<div class="col-lg-6">
<div class="row g-3">
<div class="col-6"><div class="box text-center"><div class="stat-big">40%</div><p class="muted small">Fewer emergencies</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">£1.2k</div><p class="muted small">Saved annually</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">2 wks</div><p class="muted small">Faster project delivery</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">100%</div><p class="muted small">On-time completion</p></div></div>
</div></div></div></div></section>

<!-- 11 Testimonials -->
<section class="sec" id="reviews" style="{section_alt}">
<div class="container">
<p class="text-uppercase fw-bold small accent text-center mb-2">Social proof</p>
<h2 class="display-5 fw-bold text-center mb-5">What our customers say</h2>
<div class="row g-4">{testi_html}</div></div></section>

<!-- 12 Founder note -->
<section class="sec">
<div class="container">
<div class="row g-4 align-items-center">
<div class="col-md-3 text-center"><img src="{team_img}" class="rounded-circle shadow" style="width:140px;height:140px;object-fit:cover" alt="Founder"></div>
<div class="col-md-9">
<p class="text-uppercase fw-bold small accent mb-2">A message from our director</p>
<h2 class="h3 fw-bold mb-3">We treat every home like our own</h2>
<p class="muted fs-5 mb-0">"When I started {name}, the goal was simple: offer {label_l} in {loc} that I would happily book for my own family. Thank you for trusting us — we do not take it lightly." — <strong>Director, {name}</strong></p>
</div></div></div></section>

<!-- 13 Awards -->
<section class="sec pt-0" style="{section_alt}">
<div class="container text-center">
<h2 class="h4 fw-bold mb-4">Industry validated excellence</h2>
<div>{logos}</div>
<p class="small muted mt-3">Credentials, insurance, and standards you can verify before we start.</p>
</div></section>

<!-- 14 Pricing -->
<section class="sec" id="pricing">
<div class="container">
<div class="text-center mb-5">
<h2 class="display-5 fw-bold">Simple plans for every stage</h2>
<p class="muted">Transparent pricing — final costs confirmed after we understand your exact requirements.</p>
</div>
<div class="row g-4 align-items-stretch">{pricing_html}</div></div></section>

<!-- 15 FAQ -->
<section class="sec" id="faq" style="{section_alt}">
<div class="container" style="max-width:820px">
<h2 class="display-5 fw-bold text-center mb-5">Frequently asked questions</h2>
<div class="accordion" id="faqAcc{vi}">{faq_html}</div></div></section>

<!-- 16 Team -->
<section class="sec" id="team">
<div class="container">
<h2 class="display-5 fw-bold text-center mb-2">Meet the team</h2>
<p class="text-center muted mb-5">The people behind {name} in {loc}</p>
<div class="row g-4">{team_html}</div></div></section>

<!-- 17 Blog / resources -->
<section class="sec" style="{section_alt}">
<div class="container">
<h2 class="display-5 fw-bold text-center mb-2">Latest insights &amp; strategies</h2>
<p class="text-center muted mb-5">Practical guides for {label_l} customers in {loc}</p>
<div class="row g-4">{blog_cards}</div></div></section>

<!-- 18 Map -->
<section class="sec pt-0">
<div class="container">
<h2 class="h4 fw-bold text-center mb-4">Find us in {loc}</h2>
<div class="map-placeholder d-flex align-items-center justify-content-center">
<p class="muted mb-0 px-4 text-center"><i class="bi bi-geo-alt fs-1 d-block mb-2 accent"></i>Serving {loc} and surrounding areas — contact us for exact coverage.</p>
</div></div></section>

<!-- 19 Newsletter -->
<section class="sec" style="{section_alt}">
<div class="container">
<div class="row justify-content-center">
<div class="col-lg-8 text-center">
<h2 class="h3 fw-bold mb-3">Stay ahead of the curve</h2>
<p class="muted mb-4">Monthly tips on {label_l}, maintenance, and offers for {loc} residents. No spam — unsubscribe anytime.</p>
<div class="d-flex flex-column flex-sm-row gap-2 justify-content-center">
<input type="email" class="form-control form-control-lg" style="max-width:320px" placeholder="Your email">
<button type="button" class="btn-main">Subscribe</button>
</div></div></div></div></section>

<!-- 20 Final CTA -->
<section class="sec">
<div class="container">
<div class="cta-strip text-center">
<h2 class="display-6 fw-bold mb-3">Ready to transform your next project?</h2>
<p class="lead mb-4 opacity-90">Join hundreds of satisfied clients across {loc}. Request your free quote today — we respond within hours.</p>
<a href="#contact" class="btn btn-light btn-lg fw-bold px-5">Get started now</a>
</div></div></section>

<!-- 21 Contact -->
<section class="sec" id="contact" style="{section_alt}">
<div class="container">
<div class="row g-5">
<div class="col-lg-5">
<h2 class="display-6 fw-bold mb-4">Contact {name}</h2>
<p class="muted fs-5 mb-4">Tell us about your {label_l} needs — we will reply with availability and next steps.</p>
<p><i class="bi bi-telephone accent me-2"></i><strong>0800 123 4567</strong></p>
<p><i class="bi bi-envelope accent me-2"></i><strong>hello@{email_slug}.co.uk</strong></p>
<p><i class="bi bi-clock accent me-2"></i> Mon–Sat 8am–6pm · Emergency line 24/7</p>
</div>
<div class="col-lg-7">
<div class="box">
<form class="row g-3">
<div class="col-md-6"><label class="form-label fw-semibold">Full name</label><input class="form-control" placeholder="Your name"></div>
<div class="col-md-6"><label class="form-label fw-semibold">Phone</label><input class="form-control" placeholder="07XXX XXXXXX"></div>
<div class="col-12"><label class="form-label fw-semibold">Email</label><input type="email" class="form-control" placeholder="you@email.com"></div>
<div class="col-12"><label class="form-label fw-semibold">How can we help?</label><textarea class="form-control" rows="5" placeholder="Describe your {label_l} project in {loc}…"></textarea></div>
<div class="col-12"><button type="button" class="btn-main w-100 py-3">Send enquiry</button></div>
</form></div></div></div></div></section>

<!-- 22 Footer -->
<footer class="sec pt-0 pb-5 border-top" style="border-color:rgba(128,128,128,.15)!important">
<div class="container footer-grid">
<div class="row g-4">
<div class="col-md-4">
<h3 class="fw-bold">{name}</h3>
<p class="muted">{pitch}</p>
</div>
<div class="col-md-2">
<h6 class="fw-bold">Navigate</h6>
<ul class="list-unstyled">
<li class="mb-2"><a href="#services">Services</a></li>
<li class="mb-2"><a href="#how">How it works</a></li>
<li class="mb-2"><a href="#pricing">Pricing</a></li>
<li><a href="#contact">Contact</a></li>
</ul></div>
<div class="col-md-3">
<h6 class="fw-bold">Legal</h6>
<ul class="list-unstyled muted">
<li class="mb-2">Privacy policy</li>
<li class="mb-2">Terms of service</li>
<li>Cookies</li>
</ul></div>
<div class="col-md-3">
<h6 class="fw-bold">Service area</h6>
<p class="muted">Proudly serving {loc} and nearby UK communities.</p>
</div></div>
<p class="text-center small muted mt-5 mb-0">&copy; 2026 {name}. All rights reserved. Design variation {vi + 1} of 3.</p>
</div></footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""


def generate_html(data, variation_index):
    """Premium static templates only — reliable, no Gemini/API errors."""
    print(f"  [{variation_index}] Building premium template...")
    return build_premium_html(data, variation_index)


def get_fallback_html(data, variation_index):
    return build_premium_html(data, variation_index)


# ────────────────────────────────────────────────
#  CONVERSION BANNER
# ────────────────────────────────────────────────

def inject_banner(html, site, slug, base_url):
    """Optional marketing strip (not used on final save — keeps /s/<slug> a normal page)."""
    name = site.get('business_name', 'Your Business')
    btype = site.get('business_type', 'business')
    _, _, emoji, accent = get_category_info(btype)
    dl  = f"{base_url}/download/{slug}"
    wa  = "https://wa.me/447700000000?text=I+want+to+launch+my+AI+website"

    banner = (
        "<style>"
        "#_ab{position:fixed;bottom:0;left:0;right:0;z-index:999999;"
        "background:linear-gradient(135deg,#0f172a,#1e293b);"
        "color:#fff;padding:14px 24px;display:flex;align-items:center;"
        "justify-content:space-between;gap:12px;flex-wrap:wrap;"
        "box-shadow:0 -6px 32px rgba(0,0,0,.4);"
        "font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}"
        "#_ab .l{display:flex;align-items:center;gap:10px}"
        f"#_ab .bg{{background:{accent};color:#fff;padding:3px 10px;border-radius:20px;"
        "font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase}"
        "#_ab .t{line-height:1.4}"
        "#_ab .t strong{font-size:15px;display:block}"
        "#_ab .r{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
        "#_ab a,#_ab button{padding:10px 18px;border-radius:30px;font-weight:700;"
        "font-size:13px;cursor:pointer;border:none;text-decoration:none;"
        "display:inline-flex;align-items:center;gap:5px;transition:.2s}"
        "#_ab a:hover,#_ab button:hover{transform:translateY(-2px)}"
        "#_ab .g{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}"
        "#_ab .d{background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.2)!important}"
        "#_ab .x{background:transparent;color:rgba(255,255,255,.4);font-size:18px;padding:4px 8px}"
        "body{padding-bottom:78px!important}"
        "</style>"
        f'<div id="_ab">'
        f'<div class="l"><span class="bg">AI Preview</span>'
        f'<div class="t"><strong>{name} &mdash; Your website is ready!</strong>'
        f'Our team will finalise &amp; launch it &mdash; <strong style="color:#4ade80;display:inline">completely free</strong></div></div>'
        f'<div class="r">'
        f'<a href="{wa}" target="_blank" class="g">&#128640; Launch My Site Free</a>'
        f'<a href="{dl}" class="d">&#11015; Download HTML</a>'
        f'<button class="x" onclick="document.getElementById(\'_ab\').remove();document.body.style.paddingBottom=0">&#x2715;</button>'
        f'</div></div>'
    )

    if '<meta charset' not in html.lower():
        html = html.replace('<head>', '<head>\n<meta charset="UTF-8">', 1)

    return html.replace("</body>", f"{banner}\n</body>", 1) if "</body>" in html else html + banner

# ────────────────────────────────────────────────
#  FORM PAGE  (served from backend — no file:// issues)
# ────────────────────────────────────────────────

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
input:focus,select:focus,textarea:focus{border-color:#6e8efb;box-shadow:0 0 0 4px rgba(110,142,251,0.15);transform:translateY(-1px)}
textarea{resize:vertical;min-height:100px}
.color-row{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px}
.color-item{display:flex;flex-direction:column;align-items:center;gap:6px}
.color-item input[type=color]{width:80px;height:44px;border-radius:10px;border:2px solid #e5e7eb;cursor:pointer;padding:3px}
.color-item span{font-size:11px;color:#64748b;font-weight:600}
.btn{width:100%;padding:20px;background:linear-gradient(135deg,#6e8efb,#a777e3,#6e8efb);background-size:200% auto;border:none;border-radius:18px;color:white;font-size:1.05rem;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;cursor:pointer;margin-top:28px;transition:all 0.5s}
.btn:hover{background-position:right center;transform:translateY(-3px);box-shadow:0 20px 40px rgba(110,142,251,0.4)}
.loading{display:none;position:fixed;inset:0;background:#fff;z-index:9999;flex-direction:column;align-items:center;justify-content:center}
.spinner{width:72px;height:72px;border:4px solid #f0f0f0;border-top:4px solid #6e8efb;border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:28px}
@keyframes spin{to{transform:rotate(360deg)}}
#lt{font-size:1.8rem;font-weight:800;color:#0f172a;margin-bottom:8px}
.prog-wrap{width:100%;max-width:460px;height:8px;background:#f0f0f0;border-radius:99px;overflow:hidden;margin-top:28px}
.prog-fill{height:100%;background:linear-gradient(90deg,#6e8efb,#a777e3);border-radius:99px;transition:width 0.6s ease;width:0%}
.sel-overlay{display:none;position:fixed;inset:0;background:#f8f9fa;z-index:10000;overflow-y:auto;padding:60px 20px}
.sel-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:28px;max-width:1200px;margin:40px auto}
.d-card{background:white;border-radius:20px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.08);transition:all 0.3s;cursor:pointer}
.d-card:hover{transform:translateY(-8px);box-shadow:0 28px 60px rgba(0,0,0,0.14)}
.d-preview{height:460px;width:100%;border:none;transform:scale(0.94);transform-origin:top center;pointer-events:none}
.d-info{padding:18px 22px;display:flex;justify-content:space-between;align-items:center;background:white}
.btn-sel{background:linear-gradient(135deg,#6e8efb,#a777e3);color:white;border:none;padding:12px 26px;border-radius:50px;font-weight:700;cursor:pointer;transition:all 0.3s}
.btn-sel:hover{transform:scale(1.05)}
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
    <button type="submit" class="btn">Generate 3 Unique AI Designs &rarr;</button>
  </form>
</div>
</div>

<!-- Loading -->
<div class="loading" id="ld">
  <div class="spinner"></div>
  <div id="lt">Analysing your business...</div>
  <div style="color:#64748b;font-size:0.95rem" id="ls">Building 3 unique designs for you</div>
  <div class="prog-wrap"><div class="prog-fill" id="pf"></div></div>
</div>

<!-- Selection -->
<div class="sel-overlay" id="so">
  <div style="text-align:center;margin-bottom:40px">
    <h2 style="font-size:2rem;font-weight:800;color:#0f172a;margin-bottom:8px">Choose Your Design</h2>
    <p style="color:#64748b">3 unique AI layouts — pick the one you love</p>
  </div>
  <div class="sel-grid" id="sg"></div>
</div>

<script>
const BASE = window.location.origin;
const MSGS = ['Analysing your business...','Designing Layout 1 of 3...','Building your homepage...','Designing Layout 2 of 3...','Adding colours and fonts...','Designing Layout 3 of 3...','Almost ready...'];

document.getElementById('aiform').addEventListener('submit', async e => {
  e.preventDefault();

  const fd = {
    businessName: document.getElementById('bn').value.trim(),
    businessType: document.getElementById('bt').value,
    services:     document.getElementById('sv').value.trim(),
    location:     document.getElementById('loc').value.trim(),
    style:        document.getElementById('sty').value,
    colors: [document.getElementById('c1').value, document.getElementById('c2').value, document.getElementById('c3').value]
  };

  const ld = document.getElementById('ld');
  const lt = document.getElementById('lt');
  const ls = document.getElementById('ls');
  const pf = document.getElementById('pf');
  ld.style.display = 'flex';

  let mi = 0;
  const mi_int = setInterval(() => { mi=(mi+1)%MSGS.length; lt.textContent=MSGS[mi]; }, 5000);

  function done(){ clearInterval(mi_int); }
  function fail(msg){ done(); alert('Error: '+msg); ld.style.display='none'; }

  try {
    // Register
    const r1 = await fetch(`${BASE}/api/generate-site`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(fd)
    });
    const d1 = await r1.json();
    if(!d1.success){ fail(d1.message||'Registration failed'); return; }
    const slug = d1.slug;

    const vars = [];

    // Generate each design sequentially — one request each, well within timeout
    for(let i = 0; i < 3; i++){
      lt.textContent = `Designing Layout ${i+1} of 3...`;
      ls.textContent = `This usually takes 20-30 seconds...`;
      pf.style.width = (15 + i*25)+'%';

      try {
        const r2 = await fetch(`${BASE}/api/generate-one/${slug}/${i}`);
        const d2 = await r2.json();
        if(d2.success){
          vars.push({id:i, url:d2.preview_url});
          pf.style.width = (35 + i*20)+'%';
        } else {
          console.warn('Design '+i+' failed:', d2.message);
        }
      } catch(err) {
        console.warn('Design '+i+' fetch error:', err);
      }
    }

    done();

    if(vars.length === 0){ fail('All designs failed. Please try again.'); return; }

    pf.style.width = '100%';
    lt.textContent  = vars.length+' Designs Ready!';
    ls.textContent  = 'Choose your favourite below...';

    setTimeout(() => {
      ld.style.display = 'none';
      showDesigns(slug, vars);
    }, 700);

  } catch(err){ fail(err.message); }
});

function showDesigns(slug, vars){
  const grid = document.getElementById('sg');
  grid.innerHTML = '';
  vars.forEach(v => {
    const c = document.createElement('div');
    c.className = 'd-card';
    c.innerHTML = `
      <iframe src="${v.url}" class="d-preview" loading="lazy"></iframe>
      <div class="d-info">
        <div><strong style="font-size:0.95rem">Design ${v.id+1}</strong><br><small style="color:#64748b">AI Custom Layout</small></div>
        <button class="btn-sel" onclick="pick('${slug}',${v.id})">Select This</button>
      </div>`;
    grid.appendChild(c);
  });
  document.getElementById('so').style.display='block';
  document.body.style.overflow='hidden';
}

async function pick(slug, idx){
  document.getElementById('so').style.display='none';
  const ld = document.getElementById('ld');
  const lt = document.getElementById('lt');
  ld.style.display='flex';
  lt.textContent='Finalising your website...';
  try{
    const r = await fetch(`${BASE}/api/select-design`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({slug,designIndex:idx})
    });
    const d = await r.json();
    if(d.success){ window.location = d.previewUrl; }
    else{ alert('Error: '+(d.message||'Unknown')); ld.style.display='none'; document.body.style.overflow='auto'; }
  }catch(e){ alert('Error: '+e.message); ld.style.display='none'; document.body.style.overflow='auto'; }
}
</script>
</body>
</html>"""

# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

def html_r(body, status=200):
    resp = Response(body.encode('utf-8'), status=status,
                    mimetype='text/html; charset=utf-8')
    # No frame-ancestors here — @app.after_request already strips it.
    # X-Frame-Options is also removed there. Iframes work from any origin.
    return resp

@app.route('/')
def home():
    return html_r(FORM_HTML)

@app.route('/build-with-ai')
def build_page():
    """Standalone builder on API host only; marketing site uses static build-with-ai.html."""
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

# ── Register job ──────────────────────────────────────────────────────────────
@app.route('/api/generate-site', methods=['POST', 'OPTIONS'])
def start_generation():
    if request.method == 'OPTIONS':
        return '', 204
    if not DATABASE_URL:
        return jsonify({
            "success": False,
            "message": "DATABASE_URL is not set on the server. Add it in Vercel → Project → Settings → Environment Variables.",
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
        """, (slug, data.get('businessName'), data.get('businessType','other'),
              data.get('location',''), data.get('services',''),
              data.get('style','modern'), data.get('colors',[])))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"success": True, "slug": slug})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

# ── Generate ONE design (safe per Vercel 60s limit) ───────────────────────────
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

        html = generate_html(dict(site), idx)
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

        base = request.host_url.rstrip('/')
        return jsonify({
            "success":      True,
            "variation_id": idx,
            "preview_url":  f"{base}/view-design/{slug}/{idx}",
            "html_content": html,
            "all_done":     idx == 2,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

# ── Select design ─────────────────────────────────────────────────────────────
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
        return jsonify({"success":True,"previewUrl":f"{base}/s/{slug}","downloadUrl":f"{base}/download/{slug}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

# ── View variation ────────────────────────────────────────────────────────────
@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    """Return the raw generated HTML for a design variation — NO banner, clean preview."""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        row = cur.fetchone()
        conn.close()
        if not row:
            return html_r("<h1>Not found</h1>", 404)
        return html_r(row[0])
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

# ── Final site ────────────────────────────────────────────────────────────────
@app.route('/s/<slug>')
def show_site(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s",(slug,))
        row = cur.fetchone()
        conn.close()
        if row: return html_r(row[0])
        return html_r("<h1>Not found</h1>", 404)
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

# ── Download ZIP ──────────────────────────────────────────────────────────────
@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s",(slug,))
        row = cur.fetchone()
        conn.close()
        if not row: return html_r("<h1>Not found</h1>", 404)
        buf = BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as zf:
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
        # Check if the post request has the file part
        if 'file' not in request.files:
            return jsonify({"success": False, "message": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "message": "No selected file"}), 400
        
        if file and file.filename.lower().endswith('.zip'):
            name = request.form.get('name')
            email = request.form.get('email')
            template_name = request.form.get('template_name')
            category = request.form.get('category')
            preview_url = request.form.get('preview_url')
            description = request.form.get('description')

            if not template_name or not name or not email:
                return jsonify({"success": False, "message": "Missing required fields"}), 400
            
            # Save file with timestamp prefix to prevent collisions
            import time
            timestamp = int(time.time())
            safe_tmpl_name = secure_filename(template_name)
            filename = secure_filename(f"{timestamp}_{safe_tmpl_name}_{file.filename}")
            
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            # Save to DB
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO template_submissions 
                (name, email, template_name, category, preview_url, file_path, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, email, template_name, category, preview_url, file_path, description))
            conn.commit()
            cur.close(); conn.close()
            
            return jsonify({"success": True, "message": "Template submitted successfully!"})
        else:
            return jsonify({"success": False, "message": "Only .zip files are allowed"}), 400
            
    except Exception as e:
        traceback.print_exc()
        if "permission denied" in str(e).lower():
            return jsonify({"success": False, "message": "Server storage permission error"}), 500
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)