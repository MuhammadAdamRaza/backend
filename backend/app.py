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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_applications (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                website TEXT,
                audience TEXT,
                promotion_plan TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contact_submissions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                interest TEXT,
                budget TEXT,
                message TEXT,
                source TEXT DEFAULT 'website',
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
    "plumber": {"label": "Plumbing & Heating", "hero": "https://images.unsplash.com/photo-1607472586893-edb57bdc0e39", "team": "https://images.unsplash.com/photo-1581578731548-c64695cc6952", "work": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e", "pitch": "Gas-safe minded engineers with fast call-outs, transparent quotes, and workmanship you can trust across every job."},
    "electrician": {"label": "Electrical Services", "hero": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e", "team": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e", "work": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64", "pitch": "Qualified electricians for domestic and commercial installs, fault finding, rewires, and safety certificates."},
    "restaurant": {"label": "Restaurant & Café", "hero": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4", "team": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0", "work": "https://images.unsplash.com/photo-1559339352-11d035aa65de", "pitch": "Seasonal menus, warm hospitality, and memorable dining in the heart of the community."},
    "law": {"label": "Legal Services", "hero": "https://images.unsplash.com/photo-1589829545855-d10d557cf57f", "team": "https://images.unsplash.com/photo-1560250097-0b93528c311a", "work": "https://images.unsplash.com/photo-1450101499163-c8848c66ca85", "pitch": "Clear advice, disciplined case management, and outcomes-focused representation."},
    "consulting": {"label": "Business Consulting", "hero": "https://images.unsplash.com/photo-1552664730-d307ca884978", "team": "https://images.unsplash.com/photo-1522071820081-009f0129c71c", "work": "https://images.unsplash.com/photo-1460925895917-afdab827c52f", "pitch": "Strategy, operations, and growth programmes tailored to ambitious UK small businesses."},
    "fitness": {"label": "Gym & Fitness", "hero": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48", "team": "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b", "work": "https://images.unsplash.com/photo-1517836357463-d25dfeac3438", "pitch": "Expert coaching, modern equipment, and programmes built for sustainable results."},
    "realestate": {"label": "Real Estate", "hero": "https://images.unsplash.com/photo-1560518883-ce09059eeffa", "team": "https://images.unsplash.com/photo-1560472354-b33ff0c44a43", "work": "https://images.unsplash.com/photo-1560185127-6ed189bf02f4", "pitch": "Local market insight, honest valuations, and a smooth journey from viewing to completion."},
    "agency": {"label": "Creative Agency", "hero": "https://images.unsplash.com/photo-1497366216548-37526070297c", "team": "https://images.unsplash.com/photo-1529333166437-7750a6dd4a70", "work": "https://images.unsplash.com/photo-1552664730-d307ca884978", "pitch": "Brand, web, and campaigns that help UK businesses stand out and convert more customers online."},
    "other": {"label": "Professional Services", "hero": "https://images.unsplash.com/photo-1497366754035-f200968a6e72", "team": "https://images.unsplash.com/photo-1522071820081-009f0129c71c", "work": "https://images.unsplash.com/photo-1556761175-b413da4baf72", "pitch": "Dependable expertise, transparent communication, and solutions designed around your goals."},
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

# Industry-tuned copy (fallback generator uses these when form data is sparse)
INDUSTRY_FEATURES = {
    "agency": [
        ("bi-palette", "Brand & design", "Logos, guidelines, and visuals that feel unmistakably yours."),
        ("bi-window", "Web experiences", "Fast, mobile-ready sites built to convert visitors into enquiries."),
        ("bi-megaphone", "Campaigns that convert", "Paid and organic strategies tailored to {location} audiences."),
        ("bi-graph-up", "Measurable growth", "Clear reporting so you know what is working."),
        ("bi-people", "Dedicated partner", "One team from strategy through launch — no hand-offs."),
        ("bi-shield-check", "Trusted process", "Structured timelines, approvals, and transparent pricing."),
    ],
    "restaurant": [
        ("bi-cup-hot", "Fresh ingredients", "Seasonal menus prepared with care for every service."),
        ("bi-calendar-event", "Events & catering", "Private dining and celebrations across {location}."),
        ("bi-truck", "Delivery friendly", "Reliable collection and delivery when you cannot visit."),
        ("bi-star", "Memorable hospitality", "Warm service that keeps guests coming back."),
        ("bi-clock", "Consistent hours", "Clear opening times and booking options online."),
        ("bi-geo-alt", "Local favourite", "Proudly serving {location} and the surrounding area."),
    ],
    "plumber": [
        ("bi-droplet", "Leak & burst pipes", "Fast diagnosis and lasting repairs for homes in {location}."),
        ("bi-fire", "Boilers & heating", "Servicing, installs, and emergency heating support."),
        ("bi-house", "Bathrooms & kitchens", "Tidy installs with clear quotes before we start."),
        ("bi-shield-check", "Gas-safe mindset", "Safety-first approach on every visit."),
        ("bi-clock", "Emergency slots", "Same-day call-outs when availability allows."),
        ("bi-chat-dots", "Plain-English updates", "You always know cost, scope, and arrival time."),
    ],
    "electrician": [
        ("bi-lightning", "Fault finding", "Safe testing and fixes for tripping circuits and outages."),
        ("bi-plug", "Rewires & upgrades", "Modern wiring for extensions and renovations."),
        ("bi-house-check", "EICR & compliance", "Certificates and reports for landlords and businesses."),
        ("bi-brightness-high", "Lighting design", "Indoor and outdoor lighting that suits your space."),
        ("bi-shield-check", "Fully insured", "Qualified electricians with documented work."),
        ("bi-geo-alt", "Serving {location}", "Local team with fast response across the area."),
    ],
    "fitness": [
        ("bi-heart-pulse", "Personal training", "Programmes built around your goals and schedule."),
        ("bi-people", "Small group classes", "Motivating sessions with expert coaching."),
        ("bi-calendar-check", "Flexible membership", "Options for beginners through to athletes."),
        ("bi-cup-straw", "Nutrition guidance", "Practical habits that support your training."),
        ("bi-star", "Welcoming community", "A friendly gym environment in {location}."),
        ("bi-graph-up", "Track progress", "Regular check-ins so you see real results."),
    ],
    "law": [
        ("bi-chat-square-text", "Clear advice", "Complex matters explained without jargon."),
        ("bi-file-earmark-check", "Disciplined process", "Structured case management from day one."),
        ("bi-shield-lock", "Confidential", "Your enquiry is private and without obligation."),
        ("bi-briefcase", "Business & personal", "Support for companies and individuals in {location}."),
        ("bi-clock", "Responsive", "Timely updates so you are never left wondering."),
        ("bi-award", "Outcome focused", "Practical strategies aligned to your objectives."),
    ],
}

SVC_BLURB_TEMPLATES = [
    "{svc} — a specialist service from {name} for clients in {location}. We confirm scope in writing before work begins.",
    "Our {svc} package is designed for busy households and businesses in {location} — flexible scheduling and clear updates.",
    "{name} delivers professional {svc} with qualified staff, tidy workmanship, and documentation on request.",
    "Choose {svc} with confidence: transparent quotes, no hidden extras, and friendly support from enquiry to completion.",
    "Popular in {location}: {svc} includes consultation, plain-English advice, and follow-up after the job is signed off.",
    "From first call to finish, {svc} is handled by our in-house team — we treat your property with respect.",
]

INDUSTRY_FAQ_EXTRA = {
    "agency": [("Do you offer monthly retainers?", "Yes — many {location} clients use ongoing design, web, and marketing support on a simple monthly plan.")],
    "restaurant": [("Can I book a table online?", "Yes — mention your date, time, and party size in the form and we will confirm availability.")],
    "law": [("Is the first consultation confidential?", "Absolutely. Your enquiry is private and without obligation.")],
    "plumber": [("Are you available for emergencies?", "We prioritise urgent leaks and loss of heating in {location} — call for same-day slots when available.")],
    "electrician": [("Do you issue certificates?", "Yes — EICRs, minor works, and compliance paperwork are provided where required.")],
    "fitness": [("Can I try a class first?", "Absolutely — ask about intro sessions and membership options tailored to your goals.")],
}

def _industry_key(btype):
    """Match partial business types (e.g. 'plumbing services') to industry keys."""
    bt = (btype or "other").lower().strip()
    for key in INDUSTRY:
        if key in bt:
            return key
    for key in INDUSTRY_FEATURES:
        if key in bt:
            return key
    for key in INDUSTRY_FAQ_EXTRA:
        if key in bt:
            return key
    return "other"


def _build_faq_html(vi, loc_raw, name_raw, btype):
    loc_e, name_e = _e(loc_raw), _e(name_raw)
    faqs = [
        (f"How quickly can you help in {loc_e}?", f"Most enquiries receive a reply within 2 hours. Emergency and same-day slots are often available — call us for live availability."),
        ("Are quotes free and without obligation?", "Yes. We provide clear written estimates before any work begins so you can decide with confidence."),
        (f"Which areas do you cover?", f"We serve {loc_e} and surrounding postcodes. Send your address and we will confirm coverage immediately."),
        (f"What makes {name_e} different?", "Transparent pricing, qualified staff, tidy workmanship, and communication in plain English from start to finish."),
        ("How do I pay?", "Bank transfer, card, and invoice options for trade clients. Payment terms are explained on every quote."),
        ("Do you offer guarantees?", "Yes — workmanship guarantees are included on eligible services and documented in your quote."),
    ]
    key = _industry_key(btype)
    for q_tpl, a_tpl in INDUSTRY_FAQ_EXTRA.get(key, []):
        faqs.append((q_tpl, a_tpl.format(location=loc_e, name=name_e)))
    html = ""
    for i, (q, a) in enumerate(faqs[:8]):
        html += (
            f'<div class="accordion-item acc-item">'
            f'<h2 class="accordion-header"><button class="accordion-button collapsed" type="button" '
            f'data-bs-toggle="collapse" data-bs-target="#fq{vi}{i}">{q}</button></h2>'
            f'<div id="fq{vi}{i}" class="accordion-collapse collapse" data-bs-parent="#faqAcc{vi}">'
            f'<div class="accordion-body muted">{_e(a)}</div></div></div>'
        )
    return html

DEFAULT_HERO_IMG = (
    "https://images.unsplash.com/photo-1497366754035-f200968a6e72"
    "?auto=format&fit=crop&w=1600&q=85"
)
IMG_ATTRS = 'referrerpolicy="no-referrer" crossorigin="anonymous" loading="eager" decoding="async"'


def _unsplash(url_base):
    """Reliable Unsplash URL with sizing params."""
    base = url_base.split("?")[0]
    return f"{base}?auto=format&fit=crop&w=1600&q=85"


def _hero_bg_style(hero_img):
    url = _unsplash(hero_img) if hero_img else DEFAULT_HERO_IMG
    return (
        f"background-image:url('{url}');"
        "background-position:center;background-size:cover;background-repeat:no-repeat;"
    )


def _hero_img_tag(hero_img, alt, css_class="img-fluid", extra_style=""):
    url = _unsplash(hero_img) if hero_img else DEFAULT_HERO_IMG
    fb = _unsplash(DEFAULT_HERO_IMG)
    return (
        f'<img src="{url}" alt="{alt}" class="{css_class}" {IMG_ATTRS} '
        f'style="{extra_style}" '
        f"onerror=\"this.onerror=null;this.src='{fb}'\">"
    )


def _hero_overlay(primary, secondary, bg, vi):
    """Tinted overlay — Landia light wash, Divi cinematic dark, brutal side gradient."""
    if vi == 0:
        return (
            f"linear-gradient(180deg, {_hex_mix(bg, '#ffffff', 0.15)}ee 0%, "
            f"{_hex_mix(primary, '#ffffff', 0.35)}99 50%, {_hex_mix(secondary, '#ffffff', 0.2)}bb 100%)"
        )
    if vi == 1:
        return (
            f"linear-gradient(180deg, {_hex_mix(primary, '#000000', 0.55)}99 0%, "
            f"{_hex_mix(bg, '#000000', 0.35)}cc 45%, {_hex_mix(secondary, '#000000', 0.2)}88 100%)"
        )
    if vi == 2:
        return (
            f"linear-gradient(90deg, {_hex_mix(primary, '#000000', 0.5)}cc 0%, "
            f"{_hex_mix(secondary, '#000000', 0.35)}88 40%, transparent 62%)"
        )
    return (
        f"linear-gradient(135deg, {_hex_mix(primary, '#000000', 0.65)}cc 0%, "
        f"{_hex_mix(secondary, '#000000', 0.5)}99 45%, {_hex_mix(bg, '#000000', 0.25)}88 100%)"
    )


def _parse_services(raw):
    """Accept comma lists, new lines, bullets, or numbered lines from the form."""
    if isinstance(raw, list):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        text = str(raw or "").replace("\r\n", "\n")
        chunks = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^[\-\*\u2022\d]+[\.\)\]]\s*", "", line)
            if "," in line and len(line) > 40:
                chunks.extend(s.strip() for s in line.split(",") if s.strip())
            else:
                chunks.append(line)
        if not chunks:
            chunks = [s.strip() for s in text.replace("\n", ",").split(",") if s.strip()]
        items = chunks
    if not items:
        items = ["Free consultation", "Professional service", "Ongoing support"]
    while len(items) < 3:
        items.append(items[-1])
    return items[:8]


def _svc_blurb(svc, index, location, btype, business_name):
    tpl = SVC_BLURB_TEMPLATES[index % len(SVC_BLURB_TEMPLATES)]
    return tpl.format(svc=_e(svc), name=_e(business_name), location=_e(location))


def _features_for_industry(btype, location):
    loc_e = _e(location)
    key = _industry_key(btype)
    rows = INDUSTRY_FEATURES.get(key)
    if rows:
        return [(icon, _e(title), _e(desc.format(location=loc_e))) for icon, title, desc in rows]
    return [(icon, _e(title), _e(desc.format(location=loc_e))) for icon, title, desc in FEATURES[:6]]


def _parse_colors(raw):
    if isinstance(raw, list) and len(raw) >= 2:
        return str(raw[0] or "#2563eb").strip(), str(raw[1] or "#7c3aed").strip(), str(raw[2] if len(raw) > 2 else "#f8fafc").strip()
    return "#2563eb", "#7c3aed", "#f8fafc"


def _hex_norm(c):
    c = str(c or "#2563eb").strip()
    if not c.startswith("#"):
        c = "#" + c
    if len(c) == 4:
        c = "#" + "".join(x * 2 for x in c[1:])
    return c[:7] if len(c) >= 7 else "#2563eb"


def _hex_rgb(c):
    h = _hex_norm(c)[1:]
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _hex_mix(c1, c2, t):
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _hex_rgb(c1)
    r2, g2, b2 = _hex_rgb(c2)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def _hex_lum(c):
    r, g, b = _hex_rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _theme(vi, primary, secondary, surface):
    """Each variation tints from the user's form colours — vi=0 Landia light, vi=1 Divi dark, vi=2 brutal."""
    primary, secondary, surface = _hex_norm(primary), _hex_norm(secondary), _hex_norm(surface)
    if vi == 0:
        bg = surface if _hex_lum(surface) > 0.55 else "#f8fafc"
        card = "#ffffff"
        text = "#0f172a" if _hex_lum(bg) > 0.58 else "#f1f5f9"
        muted = _hex_mix(primary, "#64748b", 0.55)
        alt = _hex_mix(surface, primary, 0.12)
    elif vi == 1:
        bg = _hex_mix(primary, "#000000", 0.78)
        card = _hex_mix(primary, "#ffffff", 0.14)
        text = "#f8fafc"
        muted = _hex_mix(secondary, "#94a3b8", 0.45)
        alt = _hex_mix(primary, secondary, 0.22)
    else:
        bg = _hex_mix(secondary, primary, 0.62)
        card = _hex_mix(secondary, "#ffffff", 0.18)
        text = "#f8fafc" if _hex_lum(bg) < 0.5 else "#0f172a"
        muted = _hex_mix(secondary, "#cbd5e1", 0.48)
        alt = _hex_mix(secondary, primary, 0.38)
    return {"bg": bg, "text": text, "card": card, "muted": muted, "alt": alt}


SVC_ICONS = [
    "bi-wrench", "bi-tools", "bi-gear-wide-connected", "bi-house-check",
    "bi-clipboard-check", "bi-truck", "bi-star", "bi-heart-pulse",
]


def _build_services_html(vi, svcs, loc, btype, business_name):
    parts = []
    for i, svc in enumerate(svcs):
        blurb = _svc_blurb(svc, i, loc, btype, business_name)
        icon = SVC_ICONS[i % len(SVC_ICONS)]
        num = f"{i + 1:02d}"
        if vi == 2:
            rev = "flex-lg-row-reverse" if i % 2 else ""
            parts.append(
                f'<div class="svc-band box box-sharp d-lg-flex align-items-center gap-4 {rev}">'
                f'<div class="flex-shrink-0"><div class="icon-pill"><i class="bi {icon}"></i></div></div>'
                f'<div class="flex-grow-1"><span class="label-tag">Service {num}</span>'
                f'<h3 class="h3 fw-bold text-uppercase mb-2">{_e(svc)}</h3>'
                f'<p class="muted mb-0">{blurb}</p></div></div>'
            )
        elif vi == 1:
            parts.append(
                f'<div class="col-md-6 col-lg-4"><div class="box box-divi h-100">'
                f'<div class="icon-pill"><i class="bi {icon}"></i></div>'
                f'<h3 class="h5 fw-semibold mb-2">{_e(svc)}</h3>'
                f'<p class="muted mb-0 small">{blurb}</p></div></div>'
            )
        else:
            parts.append(
                f'<div class="col-md-6 col-xl-4"><div class="box box-landia h-100">'
                f'<div class="icon-pill"><i class="bi {icon}"></i></div>'
                f'<h3 class="h4 fw-bold mb-3">{_e(svc)}</h3>'
                f'<p class="muted mb-0">{blurb}</p></div></div>'
            )
    body = "".join(parts).replace("div", "div")
    if vi == 2:
        return f'<div class="v-services-stack">{body}</div>'
    return f'<div class="row g-4 grid-svc">{body}</div>'


def _build_features_html(vi, location, btype):
    parts = []
    for icon, tit, d in _features_for_industry(btype, location):
        if vi == 2:
            parts.append(
                f'<div class="feat-cell"><div class="icon-pill mb-3"><i class="bi {icon}"></i></div>'
                f'<h3 class="fw-bold text-uppercase small mb-2">{tit}</h3><p class="muted mb-0 small">{d}</p></div>'
            )
        elif vi == 1:
            parts.append(
                f'<div class="feat-cell"><div class="icon-pill mb-3"><i class="bi {icon}"></i></div>'
                f'<h3 class="h5 fw-semibold mb-2">{tit}</h3><p class="muted mb-0">{d}</p></div>'
            )
        else:
            parts.append(
                f'<div class="col-md-6 col-lg-4"><div class="box box-landia h-100">'
                f'<div class="icon-pill"><i class="bi {icon}"></i></div>'
                f'<h3 class="h5 fw-bold">{tit}</h3><p class="muted mb-0">{d}</p></div></div>'
            )
    body = "".join(parts)
    if vi == 2:
        return f'<div class="feat-bento">{body}</div>'
    if vi == 1:
        return f'<div class="feat-bento-divi">{body}</div>'
    return f'<div class="row g-4">{body}</div>'


def _build_testimonials_html(vi, loc):
    parts = []
    for person, role, quote in TESTIMONIALS:
        q = _e(quote.format(location=loc))
        role_e = _e(role.format(location=loc))
        if vi == 2:
            parts.append(
                f'<div class="col-12"><div class="box d-md-flex gap-4 align-items-center">'
                f'<div class="av flex-shrink-0 mb-3 mb-md-0">{_e(person[0])}</div>'
                f'<div><div class="text-warning mb-2">★★★★★</div>'
                f'<p class="mb-2 fs-5">"{q}"</p>'
                f'<strong>{_e(person)}</strong> · <span class="muted">{role_e}</span></div></div></div>'
            )
        elif vi == 1:
            parts.append(
                f'<div class="col-md-6"><div class="box box-divi h-100">'
                f'<div class="text-warning mb-2">★★★★★</div><p class="mb-3">"{q}"</p>'
                f'<div class="d-flex gap-2 align-items-center">'
                f'<div class="av">{_e(person[0])}</div><div><strong>{_e(person)}</strong><br>'
                f'<span class="small muted">{role_e}</span></div></div></div></div>'
            )
        else:
            parts.append(
                f'<div class="col-md-6 col-lg-3"><div class="box box-landia h-100">'
                f'<div class="text-warning mb-2">★★★★★</div><p class="mb-3">"{q}"</p>'
                f'<div class="d-flex gap-2 align-items-center">'
                f'<div class="av">{_e(person[0])}</div><div><strong class="small">{_e(person)}</strong><br>'
                f'<span class="small muted">{role_e}</span></div></div></div></div>'
            )
    return '<div class="row g-4">' + "".join(parts).replace("div", "div") + "</div>"


_PREMIUM_SECTION_ORDER = {
    0: [
        "hero", "logos", "problem", "solution", "mission", "features", "services", "how",
        "stats", "case", "reviews", "founder", "awards", "pricing", "faq", "team",
        "blog", "map", "newsletter", "cta", "contact",
    ],
    1: [
        "hero", "logos", "stats", "services", "how", "features", "problem", "solution",
        "mission", "reviews", "pricing", "case", "founder", "awards", "faq", "team",
        "blog", "map", "newsletter", "cta", "contact",
    ],
    2: [
        "hero", "services", "pricing", "features", "how", "stats", "problem", "solution",
        "mission", "reviews", "case", "founder", "awards", "faq", "team", "blog", "map",
        "newsletter", "cta", "contact",
    ],
}


def _skin(vi):
    """Per-design typography, spacing, and CSS class names."""
    skins = {
        0: {
            "layout": "skin-landia",
            "fonts": "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap",
            "font_h": "Nunito",
            "font_b": "Nunito",
            "wrap": "container",
            "hero_cls": "hero hero-landia",
            "h1": "display-3 fw-bold mb-4 lh-sm",
            "h2": "display-5 fw-bold mb-3",
            "lead": "lead fs-5 mb-4",
            "sec": "sec sec-landia",
            "box": "box box-landia",
            "nav": "nav-wrap nav-landia",
            "cta_btn": "btn-main btn-lg",
        },
        1: {
            "layout": "skin-divi",
            "fonts": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
            "font_h": "Inter",
            "font_b": "Inter",
            "wrap": "container",
            "hero_cls": "hero hero-divi",
            "h1": "h1-divi",
            "h2": "h2-divi mb-3",
            "lead": "lead-divi",
            "sec": "sec sec-divi",
            "box": "box box-divi",
            "nav": "nav-wrap nav-divi",
            "cta_btn": "btn-main btn-main-pill btn-lg",
        },
        2: {
            "layout": "skin-brutal",
            "fonts": "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap",
            "font_h": "Space Grotesk",
            "font_b": "Space Grotesk",
            "wrap": "container-fluid px-3 px-lg-5",
            "hero_cls": "hero hero-brutal",
            "h1": "hero-brutal-title mb-4",
            "h2": "h2-brutal text-uppercase fw-bold mb-4",
            "lead": "lead-brutal fs-5 mb-4",
            "sec": "sec sec-brutal",
            "box": "box box-sharp",
            "nav": "nav-wrap nav-solid",
            "cta_btn": "btn-main btn-main-block btn-lg",
        },
    }
    return skins[int(vi) % 3]


def _design_css(vi, primary, secondary, overlay, font_h, font_b):
    s = _skin(vi)
    common = f"""
:root{{--p:{primary};--s:{secondary};--bg:var(--bg);--text:var(--text);--card:var(--card);--muted:var(--muted);--alt:var(--alt)}}
*{{box-sizing:border-box}}
body{{font-family:'{font_b}',system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0}}
h1,h2,h3,.hero-serif,.h2-brutal,.hero-brutal-title{{font-family:'{font_h}',serif}}
.accent{{color:var(--p)}}
.muted{{color:var(--muted)}}
.hero{{position:relative;display:flex;align-items:center;overflow:hidden}}
.hero-img{{position:absolute;inset:0;z-index:0;background-position:center;background-size:cover;background-repeat:no-repeat}}
.hero-mask{{position:absolute;inset:0;z-index:1;background:{overlay}}}
.hero-inner{{position:relative;z-index:2;width:100%}}
.stat-big{{font-weight:800;color:var(--p);line-height:1}}
.av{{background:linear-gradient(135deg,var(--p),var(--s));color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;flex-shrink:0}}
.btn-main{{background:linear-gradient(135deg,var(--p),var(--s));color:#fff!important;font-weight:700;text-decoration:none;display:inline-block;border:none;cursor:pointer}}
.btn-ghost{{border:2px solid var(--p);color:var(--p)!important;font-weight:700;text-decoration:none;background:transparent}}
.map-placeholder{{min-height:280px;background:var(--alt) center/cover url('https://images.unsplash.com/photo-1524661135-423995f22d0b?w=800&q=60')}}
.footer-grid a{{color:var(--muted);text-decoration:none}}
.footer-grid a:hover{{color:var(--p)}}
.acc-item{{background:transparent!important;border-color:rgba(128,128,128,.15)!important}}
.acc-item .accordion-button{{background:transparent!important;color:var(--text)!important;font-weight:600}}
.form-control,.form-select{{background:var(--card);border:1px solid color-mix(in srgb,var(--p) 32%,transparent);color:var(--text)}}
.form-control:focus{{border-color:var(--p);box-shadow:0 0 0 3px color-mix(in srgb,var(--p) 22%,transparent)}}
.form-control::placeholder{{color:var(--muted);opacity:.85}}
.mobile-cta{{display:none}}
@media(max-width:991.98px){{
body{{padding-bottom:76px}}
.mobile-cta{{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:1050;justify-content:center;align-items:center;padding:14px 20px;border-radius:0;font-size:1rem;letter-spacing:.02em;box-shadow:0 -8px 32px rgba(0,0,0,.2)}}
}}
"""
    landia = """
.skin-landia{background:var(--bg);color:var(--text)}
.skin-landia .sec,.skin-landia .sec-landia{padding:clamp(64px,8vw,100px) 0}
.skin-landia .box-landia{background:var(--card);border-radius:16px;padding:clamp(24px,3vw,36px);border:1px solid color-mix(in srgb,var(--p) 12%,#e2e8f0);box-shadow:0 4px 24px rgba(15,23,42,.06);height:100%;transition:.25s}
.skin-landia .box-landia:hover{transform:translateY(-4px);box-shadow:0 16px 40px rgba(15,23,42,.1)}
.skin-landia .hero-landia{min-height:min(88vh,860px);padding-top:100px;background:var(--bg)}
.skin-landia .hero-landia .hero-mask{opacity:.35}
.skin-landia .hero-landia .hero-preview{border-radius:20px;overflow:hidden;box-shadow:0 24px 60px rgba(15,23,42,.12);border:1px solid color-mix(in srgb,var(--p) 15%,#e2e8f0)}
.skin-landia .icon-pill{width:52px;height:52px;border-radius:14px;background:color-mix(in srgb,var(--p) 12%,#fff);color:var(--p);margin-bottom:18px;font-size:1.25rem;display:flex;align-items:center;justify-content:center;border:1px solid color-mix(in srgb,var(--p) 25%,transparent)}
.skin-landia .btn-main{border-radius:999px;padding:14px 32px;box-shadow:0 8px 24px color-mix(in srgb,var(--p) 35%,transparent)}
.skin-landia .btn-ghost{border-radius:999px;padding:14px 28px}
.skin-landia .nav-landia{background:#fff;box-shadow:0 2px 16px rgba(15,23,42,.06);position:sticky;top:0;z-index:1000}
.skin-landia .nav-landia .nav-link{color:var(--text);font-weight:600;font-size:.95rem}
.skin-landia .nav-landia .navbar-brand{color:var(--p)!important;font-weight:800}
.skin-landia .logo-pill{display:inline-block;padding:10px 22px;border-radius:999px;background:var(--card);border:1px solid #e2e8f0;margin:6px;font-size:.85rem;font-weight:600;color:var(--muted)}
.skin-landia .stat-big{font-size:clamp(2rem,4vw,2.8rem);color:var(--p)}
.skin-landia .av{width:48px;height:48px;border-radius:12px}
.skin-landia .cta-strip{background:linear-gradient(120deg,var(--p),var(--s));color:#fff;border-radius:20px;padding:clamp(48px,6vw,72px)}
.skin-landia .badge-top{background:color-mix(in srgb,var(--p) 10%,#fff);color:var(--p);padding:8px 16px;border-radius:999px;font-size:.85rem;font-weight:700;border:1px solid color-mix(in srgb,var(--p) 20%,transparent)}
.skin-landia .blog-thumb{height:140px;border-radius:12px 12px 0 0;margin:-36px -36px 20px -36px;background-size:cover}
.skin-landia .grid-svc .col-md-6.col-xl-4{margin-bottom:0}
.skin-landia .how-steps-h .box-landia{text-align:center}
"""
    divi = """
.skin-divi{background:var(--bg);color:var(--text)}
.skin-divi .sec,.skin-divi .sec-divi{padding:clamp(72px,9vw,110px) 0}
.skin-divi .box-divi{background:var(--card);border-radius:12px;padding:clamp(22px,2.5vw,32px);border:1px solid color-mix(in srgb,var(--p) 35%,transparent);height:100%;transition:.2s}
.skin-divi .box-divi:hover{border-color:var(--p);box-shadow:0 0 0 1px var(--p),0 20px 50px rgba(0,0,0,.35)}
.skin-divi .hero-divi{min-height:min(92vh,900px);padding-top:88px;text-align:center}
.skin-divi .hero-divi .hero-inner{padding-bottom:2rem}
.skin-divi .h1-divi{font-size:clamp(2.2rem,5.5vw,3.75rem);font-weight:700;line-height:1.12;letter-spacing:-.03em;max-width:18ch;margin-left:auto;margin-right:auto}
.skin-divi .h1-divi .accent{display:block;background:linear-gradient(120deg,var(--p),var(--s));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.skin-divi .lead-divi{font-size:clamp(1.05rem,2vw,1.25rem);color:var(--muted);max-width:42rem;margin:1.25rem auto 0;line-height:1.65}
.skin-divi .motion-frame{margin:2.5rem auto 0;max-width:920px;padding:clamp(12px,2vw,20px);border-radius:16px;background:linear-gradient(110deg,color-mix(in srgb,var(--p) 40%,#000),var(--s),#fff);line-height:0}
.skin-divi .motion-frame img{border-radius:10px;width:100%;max-height:420px;object-fit:cover}
.skin-divi .icon-pill{width:48px;height:48px;border-radius:10px;background:color-mix(in srgb,var(--p) 22%,transparent);color:var(--p);font-size:1.1rem;display:inline-flex;align-items:center;justify-content:center;margin-bottom:14px;border:1px solid color-mix(in srgb,var(--p) 40%,transparent)}
.skin-divi .btn-main-pill{border-radius:999px;padding:14px 36px;font-weight:600}
.skin-divi .btn-ghost{border-radius:999px;border-color:color-mix(in srgb,var(--p) 55%,transparent);color:var(--text)!important;padding:14px 28px}
.skin-divi .nav-divi{backdrop-filter:blur(12px);background:color-mix(in srgb,var(--bg) 92%,transparent);border-bottom:1px solid color-mix(in srgb,var(--p) 25%,transparent);position:sticky;top:0;z-index:1000}
.skin-divi .nav-divi .nav-link{color:var(--muted);font-weight:500;font-size:.92rem}
.skin-divi .nav-divi .nav-link:hover{color:var(--text)}
.skin-divi .nav-divi .navbar-brand{font-weight:700;color:#fff!important}
.skin-divi .logo-pill{display:inline-block;padding:8px 18px;border-radius:8px;background:color-mix(in srgb,var(--p) 12%,var(--card));margin:6px;font-size:.8rem;font-weight:600;color:var(--muted);border:1px solid color-mix(in srgb,var(--p) 22%,transparent)}
.skin-divi .stat-big{font-size:clamp(2.2rem,5vw,3.2rem)}
.skin-divi .av{width:44px;height:44px;border-radius:8px}
.skin-divi .cta-strip{background:linear-gradient(120deg,var(--p),color-mix(in srgb,var(--s) 80%,#000));color:#fff;border-radius:16px;padding:clamp(48px,7vw,80px)}
.skin-divi .badge-top{background:color-mix(in srgb,var(--p) 18%,var(--card));color:var(--text);padding:8px 14px;border-radius:999px;font-size:.8rem;border:1px solid color-mix(in srgb,var(--p) 35%,transparent)}
.skin-divi .h2-divi{font-size:clamp(1.75rem,4vw,2.5rem);font-weight:600;letter-spacing:-.02em}
.skin-divi .feat-bento-divi{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.skin-divi .feat-bento-divi .feat-cell{padding:22px;border-radius:12px;border:1px solid color-mix(in srgb,var(--p) 28%,transparent);min-height:130px;background:var(--card)}
.skin-divi .pricing-divi{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.skin-divi .pricing-divi .price-card{border-radius:12px;border:1px solid color-mix(in srgb,var(--p) 30%,transparent);padding:26px;height:100%;background:var(--card)}
.skin-divi .pricing-divi .price-card.featured{border-color:var(--p);background:linear-gradient(160deg,color-mix(in srgb,var(--p) 22%,var(--card)),var(--card));transform:translateY(-6px)}
.skin-divi .sec-divi-band{background:linear-gradient(180deg,color-mix(in srgb,var(--p) 14%,var(--bg)),var(--bg))}
.skin-divi .team-row-divi{display:flex;flex-wrap:wrap;gap:2rem;justify-content:center}
.skin-divi .team-row-divi .team-person{text-align:center}
.skin-divi .team-row-divi .av{width:64px;height:64px;border-radius:50%;margin:0 auto 10px}
.skin-divi .blog-thumb{height:130px;border-radius:10px 10px 0 0;margin:-32px -32px 18px -32px;background-size:cover}
"""
    brutal = """
.skin-brutal{letter-spacing:.01em}
.skin-brutal .sec-brutal{padding:clamp(48px,6vw,80px) 0}
.skin-brutal .sec-brutal.sec-band{background:color-mix(in srgb,var(--p) 12%,var(--bg));border-top:4px solid var(--p);border-bottom:4px solid var(--p)}
.skin-brutal .box-sharp{background:var(--card);border-radius:2px;padding:clamp(20px,2.5vw,32px);border:3px solid color-mix(in srgb,var(--p) 50%,transparent);height:100%}
.skin-brutal .box-sharp:hover{border-color:var(--p)}
.skin-brutal .hero-brutal{min-height:100vh}
.skin-brutal .hero-brutal .hero-img{filter:grayscale(40%) contrast(1.1)}
.skin-brutal .hero-brutal-title{font-size:clamp(2.4rem,6vw,4.2rem);text-transform:uppercase;line-height:1.05;letter-spacing:-.03em}
.skin-brutal .lead-brutal{text-transform:none;max-width:32rem}
.skin-brutal .h2-brutal{font-size:clamp(1.5rem,3vw,2rem);letter-spacing:.06em}
.skin-brutal .label-tag{display:inline-block;text-transform:uppercase;font-size:.72rem;font-weight:700;letter-spacing:.15em;padding:6px 12px;border:2px solid var(--p);margin-bottom:1rem}
.skin-brutal .icon-pill{width:64px;height:64px;border-radius:0;background:var(--p);font-size:1.5rem;display:flex;align-items:center;justify-content:center;color:#fff}
.skin-brutal .btn-main-block{border-radius:0;padding:18px 40px;text-transform:uppercase;letter-spacing:.08em}
.skin-brutal .nav-solid{background:linear-gradient(90deg,var(--p),var(--s));border:none;position:sticky;top:0;z-index:1000}
.skin-brutal .nav-solid .navbar-brand,.skin-brutal .nav-solid .nav-link{color:#fff!important;font-weight:700;text-transform:uppercase;font-size:.8rem;letter-spacing:.06em}
.skin-brutal .nav-solid .btn-main{background:#fff!important;color:var(--p)!important;border-radius:0}
.skin-brutal .logo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px}
.skin-brutal .logo-grid span{display:block;text-align:center;padding:14px;border:2px solid var(--p);font-weight:700;font-size:.75rem;text-transform:uppercase}
.skin-brutal .stats-brutal{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:3px solid var(--p)}
.skin-brutal .stats-brutal>div{padding:clamp(20px,3vw,36px);text-align:center;border-right:2px solid var(--p)}
.skin-brutal .stats-brutal>div:last-child{border-right:none}
.skin-brutal .stat-big{font-size:clamp(2rem,5vw,3.5rem)}
.skin-brutal .av{width:56px;height:56px;border-radius:0}
.skin-brutal .svc-band{padding:clamp(32px,5vw,56px);margin-bottom:12px;border-left:8px solid var(--p)}
.skin-brutal .svc-band:nth-child(even){background:color-mix(in srgb,var(--s) 15%,var(--card));flex-direction:row-reverse}
.skin-brutal .pricing-brutal{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.skin-brutal .pricing-brutal .price-card{border:3px solid var(--p);padding:28px;height:100%}
.skin-brutal .pricing-brutal .price-card.featured{transform:scale(1.05);background:color-mix(in srgb,var(--p) 18%,var(--card));z-index:2}
.skin-brutal .steps-v .box{border-left:8px solid var(--p);border-radius:0}
.skin-brutal .feat-bento{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.skin-brutal .feat-bento .feat-cell{padding:24px;border:2px solid var(--p);min-height:140px}
.skin-brutal .cta-strip{border-radius:0;border:4px solid var(--p);background:var(--p);color:#fff;padding:3rem}
.skin-brutal .hero-split-img{border-radius:0;max-height:none!important;height:min(70vh,520px);object-fit:cover;width:100%}
""".replace("div", "div")
    brutal = brutal.replace("div", "div")
    if vi == 0:
        return common + landia
    if vi == 1:
        return common + divi
    return common + brutal


def _build_pricing_html(vi):
    tiers = [
        ("Starter", "From £99", "Straightforward jobs.", ["Site visit", "Written estimate", "Warranty"], False),
        ("Professional", "From £249", "Most popular package.", ["Priority booking", "Premium parts", "12-mo support"], True),
        ("Enterprise", "Custom", "Commercial contracts.", ["Account manager", "Flexible billing", "Maintenance"], False),
    ]
    if vi == 1:
        cards = []
        for tier, price, desc, feats, star in tiers:
            lis = "".join(f"<li>{_e(f)}</li>" for f in feats)
            fc = "price-card featured" if star else "price-card"
            cards.append(
                f'<div class="{fc}"><p class="fw-bold text-uppercase small accent mb-2">{_e(tier)}</p>'
                f'<h3 class="h2-divi mb-2">{_e(price)}</h3><p class="muted mb-3">{_e(desc)}</p>'
                f'<ul class="small muted mb-4 ps-3">{lis}</ul>'
                f'<a href="#contact" class="btn-main btn-main-pill">Select plan</a></div>'
            )
        return f'<div class="pricing-divi">{"".join(cards)}</div>'
    if vi == 2:
        cards = []
        for tier, price, desc, feats, star in tiers:
            lis = "".join(f'<li><i class="bi bi-check-lg me-2"></i>{_e(f)}</li>' for f in feats)
            fc = "price-card featured" if star else "price-card"
            cards.append(
                f'<div class="{fc}"><p class="label-tag mb-2">{_e(tier)}</p>'
                f'<h3 class="display-5 fw-bold mb-2">{_e(price)}</h3><p class="muted small mb-3">{_e(desc)}</p>'
                f'<ul class="list-unstyled small mb-4">{lis}</ul>'
                f'<a href="#contact" class="btn-main btn-main-block w-100 text-center d-block">Quote</a></div>'
            )
        return f'<div class="pricing-brutal">{"".join(cards)}</div>'
    parts = []
    for tier, price, desc, feats, star in tiers:
        lis = "".join(f'<li><i class="bi bi-check2-circle me-2"></i>{_e(f)}</li>' for f in feats)
        cls = "box box-landia featured" if star else "box box-landia"
        parts.append(
            f'<div class="col-lg-4"><div class="{cls}">'
            f'<p class="fw-bold text-uppercase small accent">{_e(tier)}</p>'
            f'<h3 class="display-6 fw-bold">{_e(price)}</h3><p class="muted">{_e(desc)}</p>'
            f'<ul class="list-unstyled mb-4">{lis}</ul>'
            f'<a href="#contact" class="btn-main w-100 text-center d-block">Get a quote</a></div></div>'
        )
    return f'<div class="row g-4 grid-pricing">{"".join(parts)}</div>'


def _build_stats_html(vi, section_alt):
    items = [
        ("15+", "Years experience"),
        ("2,400+", "Projects done"),
        ("98%", "Recommend us"),
        ("4.9", "Review score"),
    ]
    if vi == 1:
        inner = "".join(
            f'<div><div class="stat-big">{a}</div><p class="muted mb-0 small text-uppercase">{b}</p></div>'
            for a, b in items
        )
        return f'<section class="sec sec-divi-band pt-0"><div class="container container-narrow"><div class="stats-inline">{inner}</div></div></section>'
    if vi == 2:
        inner = "".join(
            f'<div><div class="stat-big">{a}</div><p class="muted mb-0 small text-uppercase">{b}</p></div>'
            for a, b in items
        )
        return f'<section class="sec sec-brutal sec-band pt-0"><div class="container-fluid px-3 px-lg-5"><div class="stats-brutal">{inner}</div></div></section>'
    cells = "".join(
        f'<div class="col-6 col-md-3"><div class="box box-landia"><div class="stat-big">{a}</div>'
        f'<p class="muted mb-0">{b}</p></div></div>'
        for a, b in items
    )
    return f'<section class="sec sec-pad-lg pt-0" style="{section_alt}"><div class="container"><div class="row g-4 text-center">{cells}</div></div></section>'.replace("div", "div")


def _build_team_html(vi):
    if vi == 1:
        parts = []
        for person, role in TEAM:
            parts.append(
                f'<div class="team-person"><div class="av">{_e(person[0])}</div>'
                f'<h3 class="h6 fw-bold mb-0">{_e(person)}</h3><p class="small muted">{_e(role)}</p></div>'
            )
        return f'<div class="team-row-divi">{"".join(parts)}</div>'
    if vi == 2:
        parts = []
        for i, (person, role) in enumerate(TEAM):
            parts.append(
                f'<div class="col-6 col-lg-3"><div class="box box-sharp text-center">'
                f'<div class="label-tag mx-auto mb-3">Team 0{i+1}</div>'
                f'<div class="av mx-auto mb-2" style="width:64px;height:64px;font-size:1.25rem">{_e(person[0])}</div>'
                f'<h3 class="fw-bold text-uppercase small mb-1">{_e(person)}</h3><p class="muted small mb-0">{_e(role)}</p></div></div>'
            )
        return f'<div class="row g-3">{"".join(parts)}</div>'
    parts = []
    for person, role in TEAM:
        parts.append(
            f'<div class="col-6 col-md-3"><div class="box box-round text-center h-100">'
            f'<div class="av mx-auto mb-3">{_e(person[0])}</div>'
            f'<h3 class="h6 fw-bold mb-1">{_e(person)}</h3><p class="small muted mb-0">{_e(role)}</p></div></div>'
        )
    return f'<div class="row g-4">{"".join(parts)}</div>'.replace("div", "div")


def _build_logos_html(vi, logos_pills, awards):
    if vi == 1:
        return '<div class="logo-line">' + "".join(f"<span>{_e(a)}</span>" for a in awards) + "</div>"
    if vi == 2:
        return '<div class="logo-grid">' + "".join(f"<span>{_e(a)}</span>" for a in awards) + "</div>"
    return f"<div>{logos_pills}</div>"


def build_premium_html(data, variation_index):
    name_raw = data.get("businessName") or data.get("business_name") or "Your Business"
    name = _e(name_raw)
    btype = (data.get("businessType") or data.get("business_type") or "other").lower()
    loc_raw = str(data.get("location") or "the UK").strip()
    loc = _e(loc_raw)
    style = (data.get("style") or "modern").lower()
    ikey = _industry_key(btype)
    ind = INDUSTRY.get(ikey, INDUSTRY["other"])
    label = _e(ind["label"])
    label_l = label.lower()
    svcs_raw = _parse_services(data.get("services"))
    primary, secondary, surface = _parse_colors(data.get("colors"))
    primary, secondary, surface = _hex_norm(primary), _hex_norm(secondary), _hex_norm(surface)
    vi = int(variation_index) % 3
    t = _theme(vi, primary, secondary, surface)
    bg, text, card, muted, alt = t["bg"], t["text"], t["card"], t["muted"], t["alt"]
    skin = _skin(vi)
    wrap, box_cls, sec_cls, h2c = skin["wrap"], skin["box"], skin["sec"], skin["h2"]
    pitch = _e(ind["pitch"])
    hero_img, team_img, work_img = ind["hero"], ind["team"], ind["work"]
    work_img_url = _unsplash(work_img)
    team_img_url = _unsplash(team_img)
    email_slug = re.sub(r"[^a-z0-9]", "", name_raw.lower()) or "hello"

    headlines = {
        "modern": [f"The smarter way to book {label_l} in {loc}", f"{name} — modern {label_l} for {loc}", f"Meet the future of {label_l} in {loc}"],
        "professional": [f"Trusted {label_l} specialists serving {loc}", f"{name} — professional {label_l} you can rely on", f"Expert {label_l} for homes and businesses in {loc}"],
        "creative": [f"Bold {label_l} that stands out in {loc}", f"{name} reimagines {label_l} in {loc}", f"Creative solutions for {label_l} in {loc}"],
        "minimal": [f"Simple, honest {label_l} in {loc}", f"{name} — clear {label_l}, done right", f"Focused {label_l} for {loc}"],
    }
    hlist = headlines.get(style, headlines["modern"])
    headline = hlist[vi]
    overlay = _hero_overlay(primary, secondary, bg, vi)
    hero_bg = _hero_bg_style(hero_img)
    hero_img_el = _hero_img_tag(hero_img, name, "img-fluid rounded-4 shadow-lg", "max-height:460px;width:100%;object-fit:cover")
    hero_split_el = _hero_img_tag(hero_img, name, "hero-split-img", "width:100%;height:100%;min-height:320px;object-fit:cover")
    hero_editorial_el = _hero_img_tag(hero_img, name, "img-fluid", "max-height:340px;width:100%;object-fit:cover")
    font_heading = skin["font_h"]
    font_body = skin["font_b"]

    services_html = _build_services_html(vi, svcs_raw, loc_raw, btype, name_raw)
    features_html = _build_features_html(vi, loc_raw, btype)
    testi_html = _build_testimonials_html(vi, loc)
    pricing_html = _build_pricing_html(vi)
    faq_html = _build_faq_html(vi, loc_raw, name_raw, btype)
    pricing_body = (
        f'<div class="row g-4 align-items-stretch">{pricing_html}</div>'
        if vi == 0 else pricing_html
    )
    og_img = _unsplash(hero_img)

    blog_cards = ""
    for title_tpl, excerpt in BLOG:
        blog_cards += (
            f'<div class="col-md-4"><div class="box {box_cls} h-100">'
            f'<div class="blog-thumb" style="background-image:url(\'{work_img_url}\')"></div>'
            f'<div class="p-4"><h3 class="h5 fw-bold">{_e(title_tpl.format(label_l=label_l, location=loc, name=name))}</h3>'
            f'<p class="muted small">{_e(excerpt.format(label_l=label_l, name=name))}</p>'
            f'<a href="#" class="accent fw-semibold">Read more →</a></div></div></div>'
        )

    team_html = _build_team_html(vi)
    team_team_inner = team_html if vi == 1 else f'<div class="row g-4">{team_html}</div>'

    logos_pills = "".join(f'<span class="logo-pill">{_e(a)}</span>' for a in AWARDS)
    logos = _build_logos_html(vi, logos_pills, AWARDS)
    nav_extra = "rounded-pill px-4" if vi in (0, 1) else ""


    hero_class = skin["hero_cls"]
    section_alt = f"background:{alt};"
    feat_hdr = "text-center mb-5 mx-auto" if vi != 2 else "mb-5"
    feat_hdr_style = ' style="max-width:720px"' if vi != 2 else ""

    h1c, lc, cta = skin["h1"], skin["lead"], skin["cta_btn"]
    if vi == 1:
        _hl = headline
        _accent, _rest = _hl, ""
        if f" in {loc}" in _hl:
            _i = _hl.index(f" in {loc}")
            _accent, _rest = _hl[:_i], _hl[_i:]
        elif " — " in _hl:
            _parts = _hl.split(" — ", 1)
            _accent, _rest = _parts[0], (" — " + _parts[1]) if len(_parts) > 1 else ""
        _h1_html = f'<span class="accent">{_accent}</span>{_rest}' if _rest else f'<span class="accent">{_hl}</span>'
        hero_body = f"""<div class="hero-divi-inner text-center">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> Serving {loc}</span>
<h1 class="{h1c}">{_h1_html}</h1>
<p class="{lc}">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4 justify-content-center">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">Services</a></div>
<p class="small muted mb-3">Trusted in {loc} · Clear quotes · 5★ rated</p>
<div class="motion-frame mt-2">{hero_img_el}</div>
</div>"""
    elif vi == 2:
        hero_body = f"""<div class="row align-items-stretch g-0 min-vh-75">
<div class="col-lg-6 p-0">{hero_split_el}</div>
<div class="col-lg-6 d-flex align-items-center ps-lg-5 py-5">
<div><span class="label-tag">{loc}</span>
<h1 class="{h1c}">{headline}</h1>
<p class="{lc}">{pitch}</p>
<div class="d-flex flex-wrap gap-3">
<a href="#contact" class="{cta}">Get quote</a>
<a href="#services" class="btn-ghost">Services</a></div></div></div></div>"""
    else:
        hero_body = f"""<div class="hero-preview"><div class="row align-items-center g-5">
<div class="col-lg-7">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> {loc}</span>
<h1 class="{h1c}">{headline}</h1>
<p class="{lc}" style="max-width:38rem">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">Services</a></div>
<p class="small muted">Trusted locally · Insured · 5★ reviews</p>
</div>
<div class="col-lg-5 d-none d-lg-block"><div class="motion-frame">{hero_img_el}</div></div></div>"""

    prob_text_col = "col-lg-6 order-lg-2" if vi == 2 else "col-lg-6"
    prob_stats_col = "col-lg-6 order-lg-1" if vi == 2 else "col-lg-6"
    sol_img_col = "col-lg-6" if vi == 2 else "col-lg-6 order-lg-2"
    sol_txt_col = "col-lg-6 order-lg-2" if vi == 2 else "col-lg-6 order-lg-1"

    if vi == 2:
        how_block = f"""<div class="steps-v d-flex flex-column gap-3">
<div class="box d-flex gap-4 align-items-start"><div class="display-4 fw-bold accent">01</div><div><h3 class="h4 fw-bold">Tell us what you need</h3><p class="muted mb-0">Call, email, or use the form below.</p></div></div>
<div class="box d-flex gap-4 align-items-start"><div class="display-4 fw-bold accent">02</div><div><h3 class="h4 fw-bold">Receive a clear plan</h3><p class="muted mb-0">Written options, timeline, and pricing.</p></div></div>
<div class="box d-flex gap-4 align-items-start"><div class="display-4 fw-bold accent">03</div><div><h3 class="h4 fw-bold">We deliver &amp; follow up</h3><p class="muted mb-0">Quality work and a check-in afterwards.</p></div></div></div>"""
    else:
        how_block = """<div class="row g-4 how-steps-h">
<div class="col-md-4"><div class="box {box_cls} text-center h-100"><div class="display-3 fw-bold accent opacity-50 mb-2">01</div><h3 class="h4 fw-bold">Tell us what you need</h3><p class="muted mb-0">Call, email, or use the form below. We ask the right questions so our visit is productive.</p></div></div>
<div class="col-md-4"><div class="box {box_cls} text-center h-100"><div class="display-3 fw-bold accent opacity-50 mb-2">02</div><h3 class="h4 fw-bold">Receive a clear plan</h3><p class="muted mb-0">Written options, timeline, and pricing — no jargon, no pressure.</p></div></div>
<div class="col-md-4"><div class="box {box_cls} text-center h-100"><div class="display-3 fw-bold accent opacity-50 mb-2">03</div><h3 class="h4 fw-bold">We deliver &amp; follow up</h3><p class="muted mb-0">Quality work, tidy finish, and a check-in afterwards.</p></div></div></div>"""
    how_block = how_block.replace("div", "div")

    if vi == 1:
        founder_block = f"""<div class="row justify-content-center text-center"><div class="col-lg-8">
{_hero_img_tag(team_img, "Founder", "rounded-circle shadow mb-4", "width:120px;height:120px;object-fit:cover;border-radius:50%")}
<p class="text-uppercase fw-bold small accent mb-2">A message from our director</p>
<h2 class="h2-divi mb-3">We treat every home like our own</h2>
<p class="muted fs-5 mb-0">"When I started {name}, the goal was simple: offer {label_l} in {loc} that I would happily book for my own family." — <strong>Director, {name}</strong></p>
</div></div>"""
    else:
        founder_block = f"""<div class="row g-4 align-items-center">
<div class="col-md-3 text-center">{_hero_img_tag(team_img, "Founder", "rounded-circle shadow", "width:140px;height:140px;object-fit:cover;border-radius:50%")}</div>
<div class="col-md-9"><p class="text-uppercase fw-bold small accent mb-2">A message from our director</p>
<h2 class="h3 fw-bold mb-3">We treat every home like our own</h2>
<p class="muted fs-5 mb-0">"When I started {name}, the goal was simple: offer {label_l} in {loc} that I would happily book for my own family. Thank you for trusting us." — <strong>Director, {name}</strong></p>
</div></div>"""

    if vi == 2:
        contact_block = f"""<div class="row g-5">
<div class="col-lg-7 order-lg-1"><div class="box {box_cls}"><form class="row g-3">
<div class="col-md-6"><label class="form-label fw-semibold">Full name</label><input class="form-control" placeholder="Your name"></div>
<div class="col-md-6"><label class="form-label fw-semibold">Phone</label><input class="form-control" placeholder="07XXX XXXXXX"></div>
<div class="col-12"><label class="form-label fw-semibold">Email</label><input type="email" class="form-control" placeholder="you@email.com"></div>
<div class="col-12"><label class="form-label fw-semibold">How can we help?</label><textarea class="form-control" rows="5" placeholder="Describe your project…"></textarea></div>
<div class="col-12"><button type="button" class="btn-main w-100 py-3">Send enquiry</button></div>
</form></div></div>
<div class="col-lg-5 order-lg-2">
<h2 class="display-6 fw-bold mb-4">Contact {name}</h2>
<p class="muted fs-5 mb-4">Tell us about your {label_l} needs in {loc}.</p>
<p><i class="bi bi-telephone accent me-2"></i><strong>0800 123 4567</strong></p>
<p><i class="bi bi-envelope accent me-2"></i><strong>hello@{email_slug}.co.uk</strong></p>
<p><i class="bi bi-clock accent me-2"></i> Mon–Sat 8am–6pm</p></div></div>"""
    else:
        contact_block = f"""<div class="row g-5">
<div class="col-lg-5">
<h2 class="display-6 fw-bold mb-4">Contact {name}</h2>
<p class="muted fs-5 mb-4">Tell us about your {label_l} needs — we will reply with availability and next steps.</p>
<p><i class="bi bi-telephone accent me-2"></i><strong>0800 123 4567</strong></p>
<p><i class="bi bi-envelope accent me-2"></i><strong>hello@{email_slug}.co.uk</strong></p>
<p><i class="bi bi-clock accent me-2"></i> Mon–Sat 8am–6pm · Emergency line 24/7</p>
</div>
<div class="col-lg-7"><div class="box {box_cls}"><form class="row g-3">
<div class="col-md-6"><label class="form-label fw-semibold">Full name</label><input class="form-control" placeholder="Your name"></div>
<div class="col-md-6"><label class="form-label fw-semibold">Phone</label><input class="form-control" placeholder="07XXX XXXXXX"></div>
<div class="col-12"><label class="form-label fw-semibold">Email</label><input type="email" class="form-control" placeholder="you@email.com"></div>
<div class="col-12"><label class="form-label fw-semibold">How can we help?</label><textarea class="form-control" rows="5" placeholder="Describe your {label_l} project in {loc}…"></textarea></div>
<div class="col-12"><button type="button" class="btn-main w-100 py-3">Send enquiry</button></div>
</form></div></div></div>"""
    contact_block = contact_block.replace("div", "div")

    stats_html = _build_stats_html(vi, section_alt)
    sec = {
        "hero": f"""<section class="{hero_class}" id="top"><div class="hero-img" style="{hero_bg}"></div><div class="hero-mask"></div><div class="{wrap} hero-inner">{hero_body}</div></section>""",
        "logos": f"""<section class="sec pt-0"><div class="container text-center"><p class="text-uppercase fw-bold small muted mb-3">Trusted by homeowners &amp; businesses</p><div>{logos}</div></div></section>""",
        "problem": f"""<section class="sec problem-grid" style="{section_alt}"><div class="container"><div class="row g-5 align-items-center">
<div class="{prob_text_col}"><p class="text-uppercase fw-bold small accent mb-2">The challenge</p>
<h2 class="display-5 fw-bold mb-4">The cost of choosing the wrong {label_l} provider</h2>
<p class="fs-5 muted">Too many people in {loc} face delayed call-outs, vague quotes, and messy workmanship.</p>
<ul class="list-unstyled fs-5"><li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Hidden fees on the day</li>
<li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Poor communication</li>
<li class="mb-3"><i class="bi bi-x-circle me-2 text-danger"></i> Work that needs redoing</li></ul></div>
<div class="{prob_stats_col}"><div class="row g-3 text-center">
<div class="col-6"><div class="box"><div class="stat-big">38%</div><p class="muted small mb-0">Bad experiences</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">£240</div><p class="muted small mb-0">Cost of fixes</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">3 days</div><p class="muted small mb-0">Typical wait</p></div></div>
<div class="col-6"><div class="box"><div class="stat-big">24/7</div><p class="muted small mb-0">Emergency line</p></div></div>
</div></div></div></section>""".replace("div", "div"),
        "solution": f"""<section class="sec"><div class="container"><div class="row g-5 align-items-center">
<div class="{sol_img_col}">{_hero_img_tag(work_img, "Our work", "img-fluid rounded-4 shadow", "width:100%;object-fit:cover")}</div>
<div class="{sol_txt_col}"><p class="text-uppercase fw-bold small accent mb-2">The solution</p>
<h2 class="display-5 fw-bold mb-4">Meet the future of {label_l} in {loc}</h2>
<p class="fs-5 muted mb-4">{name} combines qualified people and a customer-first process.</p>
<p class="muted">You always know who is coming, what it costs, and when it will be done.</p></div></div></div></section>""",
        "mission": f"""<section class="sec" style="{section_alt}"><div class="container"><div class="row justify-content-center text-center"><div class="col-lg-8">
<p class="text-uppercase fw-bold small accent mb-2">Why we build</p><h2 class="display-5 fw-bold mb-4">Our mission</h2>
<p class="fs-5 muted">We believe every client in {loc} deserves honest, fairly priced {label_l}. That is why {name} exists.</p>
</div></div></div></section>""",
        "features": f"""<section class="sec" id="features"><div class="container"><div class="{feat_hdr}"{feat_hdr_style}>
<p class="text-uppercase fw-bold small accent mb-2">Capabilities</p><h2 class="display-5 fw-bold mb-3">Everything you need</h2>
<p class="muted">Six reasons clients choose {name} in {loc}.</p></div>{features_html}</div></section>""",
        "services": f"""<section class="sec" id="services" style="{section_alt}"><div class="container">
<div class="text-center mb-5 mx-auto" style="max-width:760px"><p class="text-uppercase fw-bold small accent mb-2">Our services</p>
<h2 class="display-5 fw-bold mb-3">Comprehensive {label_l} in {loc}</h2>
<p class="muted fs-5">Your chosen services — delivered by our in-house team in {loc}.</p></div>
{services_html}</div></section>""",
        "how": f"""<section class="sec" id="how"><div class="container"><div class="text-center mb-5">
<h2 class="display-5 fw-bold">How it works — 3 simple steps</h2><p class="muted">From enquiry to completion.</p></div>{how_block}</div></section>""",
        "stats": stats_html,
        "case": f"""<section class="sec"><div class="container"><div class="row g-5 align-items-center">
<div class="col-lg-6"><p class="text-uppercase fw-bold small accent mb-2">Results</p><h2 class="display-5 fw-bold mb-4">Real data. Real growth.</h2>
<p class="muted fs-5">A client in {loc} reduced repeat call-outs by 40% with our maintenance programme.</p></div>
<div class="col-lg-6"><div class="row g-3">
<div class="col-6"><div class="box text-center"><div class="stat-big">40%</div><p class="muted small">Fewer emergencies</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">£1.2k</div><p class="muted small">Saved yearly</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">2 wks</div><p class="muted small">Faster delivery</p></div></div>
<div class="col-6"><div class="box text-center"><div class="stat-big">100%</div><p class="muted small">On time</p></div></div>
</div></div></div></section>""".replace("div", "div"),
        "reviews": f"""<section class="sec" id="reviews" style="{section_alt}"><div class="container">
<p class="text-uppercase fw-bold small accent text-center mb-2">Social proof</p>
<h2 class="display-5 fw-bold text-center mb-5">What our customers say</h2>{testi_html}</div></section>""",
        "founder": f"""<section class="sec"><div class="container">{founder_block}</div></section>""",
        "awards": f"""<section class="sec pt-0" style="{section_alt}"><div class="container text-center">
<h2 class="h4 fw-bold mb-4">Industry validated excellence</h2><div>{logos}</div>
<p class="small muted mt-3">Credentials you can verify before we start.</p></div></section>""".replace("div", "div"),
        "pricing": f"""<section class="sec" id="pricing"><div class="container"><div class="text-center mb-5">
<h2 class="display-5 fw-bold">Simple plans for every stage</h2><p class="muted">Transparent pricing for {loc}.</p></div>
{pricing_body}</div></section>""",
        "faq": f"""<section class="sec" id="faq" style="{section_alt}"><div class="container" style="max-width:820px">
<h2 class="display-5 fw-bold text-center mb-5">FAQ</h2><div class="accordion" id="faqAcc{vi}">{faq_html}</div></div></section>""",
        "team": f"""<section class="sec" id="team"><div class="container"><h2 class="display-5 fw-bold text-center mb-2">Meet the team</h2>
<p class="text-center muted mb-5">The people behind {name}</p>{team_team_inner}</div></section>""",
        "blog": f"""<section class="sec" style="{section_alt}"><div class="container"><h2 class="display-5 fw-bold text-center mb-2">Latest insights</h2>
<p class="text-center muted mb-5">Guides for {label_l} in {loc}</p><div class="row g-4">{blog_cards}</div></div></section>""",
        "map": f"""<section class="sec pt-0"><div class="container"><h2 class="h4 fw-bold text-center mb-4">Find us in {loc}</h2>
<div class="map-placeholder d-flex align-items-center justify-content-center"><p class="muted mb-0 px-4 text-center"><i class="bi bi-geo-alt fs-1 d-block mb-2 accent"></i>Serving {loc} and nearby areas.</p></div></div></section>""",
        "newsletter": f"""<section class="sec" style="{section_alt}"><div class="container"><div class="row justify-content-center"><div class="col-lg-8 text-center">
<h2 class="h3 fw-bold mb-3">Stay ahead of the curve</h2><p class="muted mb-4">Tips for {loc} — unsubscribe anytime.</p>
<div class="d-flex flex-column flex-sm-row gap-2 justify-content-center">
<input type="email" class="form-control form-control-lg" style="max-width:320px" placeholder="Your email">
<button type="button" class="btn-main">Subscribe</button></div></div></div></div></section>""",
        "cta": f"""<section class="sec"><div class="container"><div class="cta-strip text-center">
<h2 class="display-6 fw-bold mb-3">Ready to get started?</h2>
<p class="lead mb-4 opacity-90">Request your free quote — we respond within hours.</p>
<a href="#contact" class="btn btn-light btn-lg fw-bold px-5">Get started now</a></div></div></section>""".replace("div", "div"),
        "contact": f"""<section class="sec" id="contact" style="{section_alt}"><div class="container">{contact_block}</div></section>""",
    }
    if vi in (0, 1):
        for _k in sec:
            sec[_k] = (
                sec[_k]
                .replace('class="box"', f'class="{box_cls}"')
                .replace('class="display-5 fw-bold', f'class="{h2c}"')
                .replace('class="sec ', f'class="{sec_cls} ')
            )
        if vi == 1:
            for _k in sec:
                sec[_k] = sec[_k].replace('class="display-6 fw-bold', f'class="{h2c}"')
    main_body = "".join(sec[k] for k in _PREMIUM_SECTION_ORDER[vi])

    return f"""<!DOCTYPE html>
<html lang="en-GB" class="theme-{vi} {skin['layout']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} | {label} — {loc}</title>
<meta name="description" content="{name} — {pitch} Serving {loc}.">
<meta property="og:title" content="{name} | {label} — {loc}">
<meta property="og:description" content="{pitch}">
<meta property="og:type" content="website">
<meta property="og:image" content="{og_img}">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<link href="{skin['fonts']}" rel="stylesheet">
<style>{_design_css(vi, primary, secondary, overlay, skin['font_h'], skin['font_b'])}</style>
</head>
<body>
<header class="{skin['nav']}">
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
{main_body}
<a href="#contact" class="mobile-cta btn-main" aria-label="Request a free quote">Free quote</a>
<footer class="sec pt-0 pb-5 border-top" style="border-color:rgba(128,128,128,.15)!important">
<div class="container footer-grid">
<div class="row g-4">
<div class="col-md-4"><h3 class="fw-bold">{name}</h3><p class="muted">{pitch}</p></div>
<div class="col-md-2"><h6 class="fw-bold">Navigate</h6><ul class="list-unstyled">
<li class="mb-2"><a href="#services">Services</a></li><li class="mb-2"><a href="#how">How it works</a></li>
<li class="mb-2"><a href="#pricing">Pricing</a></li><li><a href="#contact">Contact</a></li></ul></div>
<div class="col-md-3"><h6 class="fw-bold">Legal</h6><ul class="list-unstyled muted">
<li class="mb-2">Privacy policy</li><li class="mb-2">Terms of service</li><li>Cookies</li></ul></div>
<div class="col-md-3"><h6 class="fw-bold">Service area</h6><p class="muted">Serving {loc} and nearby UK communities.</p></div></div>
<p class="text-center small muted mt-5 mb-0">&copy; 2026 {name}. Design {vi + 1} of 3 — your brand colours applied.</p>
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
.hint{font-size:0.8125rem;color:#6b7280;margin:-4px 0 8px;line-height:1.45}
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
      <label>Services *</label>
      <p class="hint">Enter your services here in full so we can generate your website template.</p>
      <textarea id="sv" placeholder="e.g. Brand strategy, Web design, Social media management" required></textarea>
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


@app.route('/api/submit-affiliate', methods=['POST', 'OPTIONS'])
def submit_affiliate():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or request.form.get('name') or '').strip()
        email = (data.get('email') or request.form.get('email') or '').strip()
        website = (data.get('website') or request.form.get('website') or '').strip()
        audience = (data.get('audience') or request.form.get('audience') or '').strip()
        plan = (data.get('plan') or request.form.get('plan') or '').strip()

        if not name or not email or not website or not audience or not plan:
            return jsonify({"success": False, "message": "Please fill in all required fields."}), 400

        _lazy_init_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO affiliate_applications (name, email, website, audience, promotion_plan)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (name, email, website, audience, plan),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "Application received. We will email you within a few working days."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


@app.route('/api/submit-contact', methods=['POST', 'OPTIONS'])
def submit_contact():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or request.form.get('name') or '').strip()
        email = (data.get('email') or request.form.get('email') or '').strip()
        interest = (data.get('interest') or request.form.get('interest') or '').strip()
        budget = (data.get('budget') or request.form.get('budget') or '').strip()
        message = (data.get('message') or request.form.get('message') or '').strip()
        source = (data.get('source') or request.form.get('source') or 'website').strip()

        if not name or not email or not message:
            return jsonify({"success": False, "message": "Name, email, and message are required."}), 400

        _lazy_init_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO contact_submissions (name, email, interest, budget, message, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, email, interest, budget, message, source or 'website'),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "success": True,
            "message": "Message received. We will get back to you within one to two working days.",
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)