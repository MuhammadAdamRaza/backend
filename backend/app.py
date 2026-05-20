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
                country TEXT,
                monthly_traffic TEXT,
                audience TEXT,
                promotion_plan TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            ALTER TABLE affiliate_applications ADD COLUMN IF NOT EXISTS country TEXT;
        """)
        cur.execute("""
            ALTER TABLE affiliate_applications ADD COLUMN IF NOT EXISTS monthly_traffic TEXT;
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS site_pages (
                site_slug TEXT REFERENCES sites(slug) ON DELETE CASCADE,
                filename TEXT,
                html_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (site_slug, filename)
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
            "h1": "display-3 fw-bold mb-4 lh-sm text-text",
            "h2": "display-5 fw-bold mb-3 text-text",
            "lead": "lead fs-5 mb-4 text-muted",
            "sec": "sec sec-landia",
            "box": "box box-landia",
            "nav": "nav-wrap nav-landia",
            "cta_btn": "btn btn-primary btn-lg rounded-pill shadow-sm px-5 py-3",
        },
        1: {
            "layout": "skin-divi",
            "fonts": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
            "font_h": "Inter",
            "font_b": "Inter",
            "wrap": "container",
            "hero_cls": "hero hero-divi",
            "h1": "display-1 fw-bold mb-4 lh-1 text-text tracking-tight",
            "h2": "display-4 fw-bold mb-4 text-text",
            "lead": "lead fs-4 mb-5 text-muted",
            "sec": "sec sec-divi",
            "box": "box box-divi glass-card",
            "nav": "nav-wrap nav-divi glass-nav",
            "cta_btn": "btn btn-light btn-lg rounded-pill shadow-lg px-5 py-3 fw-bold text-primary",
        },
        2: {
            "layout": "skin-brutal",
            "fonts": "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap",
            "font_h": "Space Grotesk",
            "font_b": "Space Grotesk",
            "wrap": "container-fluid px-4 px-lg-5",
            "hero_cls": "hero hero-brutal",
            "h1": "display-1 fw-black text-uppercase mb-4 lh-1 brutal-title text-text",
            "h2": "display-3 fw-black text-uppercase mb-4 brutal-heading text-text",
            "lead": "fs-4 mb-5 brutal-lead fw-bold text-text",
            "sec": "sec sec-brutal",
            "box": "box box-sharp brutal-border",
            "nav": "nav-wrap nav-solid brutal-nav border-bottom border-text border-3",
            "cta_btn": "btn btn-dark brutal-btn-dark btn-lg brutal-btn px-5 py-3 text-uppercase fw-bold rounded-0 border border-3 border-text",
        },
    }
    return skins[int(vi) % 3]


def _design_css(vi, primary, secondary, overlay, font_h, font_b):
    common = f"""
:root{{--p:{primary};--s:{secondary};--bg:var(--bg);--text:var(--text);--card:var(--card);--muted:var(--muted);--alt:var(--alt)}}
*{{box-sizing:border-box}}
body{{font-family:'{font_b}',system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;overflow-x:hidden;}}
h1,h2,h3,h4,h5,h6{{font-family:'{font_h}',serif; color:var(--text);}}
.accent{{color:var(--p)}}
.text-text{{color:var(--text)!important;}}
.text-muted{{color:var(--muted)!important;}}
.bg-bg{{background-color:var(--bg)!important;}}
.bg-card{{background-color:var(--card)!important;}}
.bg-alt{{background-color:var(--alt)!important;}}
.hero{{position:relative;display:flex;align-items:center;overflow:hidden;width:100%}}
.hero-img{{position:absolute;inset:0;z-index:0;background-position:center;background-size:cover;background-repeat:no-repeat}}
.hero-mask{{position:absolute;inset:0;z-index:1;background:{overlay}}}
.hero-inner{{position:relative;z-index:2;width:100%}}
.btn-primary {{background-color: var(--p) !important; border-color: var(--p) !important; color:#fff!important;}}
.btn-outline-primary {{border-color: var(--p) !important; color:var(--p)!important;}}
.btn-outline-primary:hover {{background-color: var(--p) !important; color:#fff!important;}}
.text-primary {{color: var(--p) !important;}}
.bg-primary {{background-color: var(--p) !important;}}
.footer-grid a{{color:var(--muted);text-decoration:none;transition:all 0.2s;}}
.footer-grid a:hover{{color:var(--p)}}
img {{max-width: 100%; height: auto;}}
.accordion-button{{background-color:var(--card); color:var(--text);}}
.accordion-button:not(.collapsed){{background-color:color-mix(in srgb, var(--p) 10%, var(--card)); color:var(--p);}}
.form-control {{background-color:var(--card); border: 1px solid var(--alt); color:var(--text);}}
.form-control:focus {{border-color:var(--p); box-shadow: 0 0 0 0.25rem color-mix(in srgb, var(--p) 25%, transparent); background-color:var(--card); color:var(--text);}}
"""
    landia = """
.skin-landia .sec {padding: 6rem 0;}
.skin-landia .box-landia {background: var(--card); border-radius: 1rem; padding: 2.5rem; border: 1px solid var(--alt); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); transition: transform 0.3s ease, box-shadow 0.3s ease; height: 100%;}
.skin-landia .box-landia:hover {transform: translateY(-5px); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);}
.skin-landia .hero-landia {min-height: 80vh; background: var(--alt);}
.skin-landia .nav-landia {background: var(--bg); box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1); position: sticky; top: 0; z-index: 1030;}
.skin-landia .nav-landia .nav-link {color: var(--muted); font-weight: 600;}
.skin-landia .nav-landia .nav-link:hover {color: var(--p);}
.skin-landia .img-float {animation: float 6s ease-in-out infinite; border-radius: 1.5rem; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);}
@keyframes float { 0% { transform: translateY(0px); } 50% { transform: translateY(-20px); } 100% { transform: translateY(0px); } }
.skin-landia .section-title {position: relative; padding-bottom: 1rem; margin-bottom: 3rem;}
.skin-landia .section-title::after {content: ''; position: absolute; left: 0; bottom: 0; width: 60px; height: 4px; background: var(--p); border-radius: 2px;}
.skin-landia .text-center .section-title::after {left: 50%; transform: translateX(-50%);}
.skin-landia .team-img {width: 120px; height: 120px; object-fit: cover; border-radius: 50%; border: 4px solid var(--card); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);}
"""
    divi = """
.skin-divi .sec {padding: 8rem 0;}
.skin-divi .glass-card {background: color-mix(in srgb, var(--card) 60%, transparent); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border: 1px solid color-mix(in srgb, var(--text) 5%, transparent); border-radius: 1.5rem; padding: 3rem; transition: all 0.3s ease; height: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.1);}
.skin-divi .glass-card:hover {background: color-mix(in srgb, var(--card) 80%, transparent); transform: translateY(-5px); border-color: color-mix(in srgb, var(--p) 20%, transparent);}
.skin-divi .hero-divi {min-height: 100vh; background: radial-gradient(circle at top right, color-mix(in srgb, var(--p) 15%, transparent), var(--bg) 60%);}
.skin-divi .hero-divi::before {content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0IiBoZWlnaHQ9IjQiPgo8cmVjdCB3aWR0aD0iNCIgaGVpZ2h0PSI0IiBmaWxsPSIjZmZmIiBmaWxsLW9wYWNpdHk9IjAuMDUiLz4KPC9zdmc+') repeat; opacity: 0.1; z-index:0;}
.skin-divi .glass-nav {background: color-mix(in srgb, var(--bg) 80%, transparent); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid color-mix(in srgb, var(--text) 5%, transparent); position: sticky; top: 0; z-index: 1030;}
.skin-divi .glass-nav .nav-link {color: var(--muted); font-weight: 500;}
.skin-divi .glass-nav .nav-link:hover {color: var(--text);}
.skin-divi .glow-img {border-radius: 2rem; box-shadow: 0 0 60px color-mix(in srgb, var(--p) 25%, transparent); border: 1px solid color-mix(in srgb, var(--text) 5%, transparent);}
.skin-divi .text-gradient {background: linear-gradient(135deg, var(--text) 0%, color-mix(in srgb, var(--text) 70%, transparent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;}
.skin-divi .team-img {width: 140px; height: 140px; object-fit: cover; border-radius: 1.5rem; margin-bottom: -40px; position: relative; z-index: 1; border: 4px solid var(--bg);}
.skin-divi .pricing-featured {transform: scale(1.05); background: radial-gradient(circle at top right, color-mix(in srgb, var(--p) 10%, var(--card)), var(--card)); border-color: var(--p);}
"""
    brutal = """
.skin-brutal {letter-spacing: -0.02em;}
.skin-brutal .sec {padding: 7rem 0; border-bottom: 3px solid var(--text);}
.skin-brutal .box-sharp {background: var(--card); padding: 2.5rem; border: 3px solid var(--text); box-shadow: 8px 8px 0px 0px var(--text); transition: all 0.2s ease; height: 100%;}
.skin-brutal .box-sharp:hover {transform: translate(-4px, -4px); box-shadow: 12px 12px 0px 0px var(--p);}
.skin-brutal .hero-brutal {min-height: 90vh; background: var(--alt); border-bottom: 4px solid var(--text);}
.skin-brutal .brutal-nav {background: var(--bg);}
.skin-brutal .brutal-nav .nav-link {color: var(--text); font-weight: 700; text-transform: uppercase; letter-spacing: 1px;}
.skin-brutal .brutal-nav .nav-link:hover {background: var(--text); color: var(--bg);}
.skin-brutal .brutal-btn {box-shadow: 6px 6px 0px 0px var(--p); transition: all 0.2s ease;}
.skin-brutal .brutal-btn:hover {transform: translate(2px, 2px); box-shadow: 4px 4px 0px 0px var(--p);}
.skin-brutal .brutal-btn-dark {background: var(--text)!important; color: var(--bg)!important; border-color: var(--text)!important; box-shadow: 6px 6px 0px 0px var(--p);}
.skin-brutal .brutal-img {border: 4px solid var(--text); box-shadow: 12px 12px 0px 0px var(--text);}
.skin-brutal .fw-black {font-weight: 900;}
.skin-brutal .marquee {white-space: nowrap; overflow: hidden; box-sizing: border-box; background: var(--text); color: var(--bg); padding: 1rem 0; border-top: 3px solid var(--text); border-bottom: 3px solid var(--text);}
.skin-brutal .marquee span {display: inline-block; padding-left: 100%; text-transform: uppercase; font-weight: 900; font-size: 1.5rem; animation: marquee 15s linear infinite;}
@keyframes marquee { 0% { transform: translate(0, 0); } 100% { transform: translate(-100%, 0); } }
.skin-brutal .team-img {width: 100%; aspect-ratio: 1; object-fit: cover; border: 3px solid var(--text); border-bottom: none;}
"""
    if vi == 0: return common + landia
    if vi == 1: return common + divi
    return common + brutal

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
    wrap, box_cls, sec_cls, h2c, h1c, lc, cta = skin["wrap"], skin["box"], skin["sec"], skin["h2"], skin["h1"], skin["lead"], skin["cta_btn"]
    pitch = _e(ind["pitch"])
    hero_img = _unsplash(ind["hero"])
    work_img = _unsplash(ind["work"])
    team_img = _unsplash(ind["team"])
    email_slug = re.sub(r"[^a-z0-9]", "", name_raw.lower()) or "hello"

    overlay = _hero_overlay(primary, secondary, bg, vi)
    hero_bg = _hero_bg_style(hero_img)

    # Base HTML Structure (Head & Nav)
    html_head = f"""<!DOCTYPE html>
<html lang="en-GB" class="theme-{vi} {skin['layout']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} | {label} — {loc}</title>
<meta name="description" content="{name} — {pitch} Serving {loc}.">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<link href="{skin['fonts']}" rel="stylesheet">
<style>{_design_css(vi, primary, secondary, overlay, skin['font_h'], skin['font_b'])}</style>
</head>
<body class="bg-bg">
<header class="{skin['nav']}">
<nav class="navbar navbar-expand-lg py-3">
<div class="container">
<a class="navbar-brand fw-bold fs-4 text-text" href="#">{name}</a>
<button class="navbar-toggler border-0" type="button" data-bs-toggle="collapse" data-bs-target="#mainNav" aria-controls="mainNav" aria-expanded="false" aria-label="Toggle navigation">
    <i class="bi bi-list fs-1 text-text"></i>
</button>
<div class="collapse navbar-collapse bg-bg p-3 p-lg-0 rounded-3 shadow-sm shadow-lg-none mt-2 mt-lg-0" id="mainNav">
<ul class="navbar-nav ms-auto align-items-lg-center gap-lg-3">
<li class="nav-item"><a class="nav-link" href="#problem">Why Us</a></li>
<li class="nav-item"><a class="nav-link" href="#services">Services</a></li>
<li class="nav-item"><a class="nav-link" href="#pricing">Pricing</a></li>
<li class="nav-item"><a class="nav-link" href="#team">Team</a></li>
<li class="nav-item"><a class="nav-link" href="#faq">FAQ</a></li>
<li class="nav-item mt-2 mt-lg-0"><a class="{cta.replace('btn-lg', 'btn-sm py-2 px-4')} w-100 w-lg-auto text-center" href="#contact">Contact Us</a></li>
</ul></div></div></nav>
</header>
"""
    # -------------------------------------------------------------------------
    # LAYOUT 0: Modern Startup (12 Sections)
    # -------------------------------------------------------------------------
    if vi == 0:
        svcs_html = "".join([f'<div class="col-md-6 col-lg-4"><div class="{box_cls}"><i class="bi bi-check-circle-fill text-primary fs-2 mb-3"></i><h3 class="h5 fw-bold text-text">{_e(s["title"])}</h3><p class="text-muted mb-0">{_e(s["desc"])}</p></div></div>' for s in svcs_raw[:6]])
        body_html = f"""
<section class="hero hero-landia" id="hero">
    <div class="container h-100">
        <div class="row h-100 align-items-center g-5 py-5">
            <div class="col-lg-6 order-2 order-lg-1">
                <span class="badge bg-primary text-white rounded-pill px-3 py-2 mb-4 fw-semibold shadow-sm">Top Rated {label_l} in {loc}</span>
                <h1 class="{h1c}">{name} — {label}</h1>
                <p class="{lc}">{pitch}</p>
                <div class="d-flex flex-column flex-sm-row gap-3 mt-4">
                    <a href="#contact" class="{cta}">Get a Free Quote</a>
                    <a href="#services" class="btn btn-outline-primary btn-lg rounded-pill px-5 py-3 fw-bold bg-bg">Explore Services</a>
                </div>
                <div class="d-flex align-items-center gap-4 mt-5">
                    <img src="{team_img}" class="rounded-circle border border-2 border-white shadow-sm" width="48" height="48" style="object-fit:cover" alt="User">
                    <div><p class="mb-0 fw-bold text-text">4.9/5 Average Rating</p><p class="small text-muted mb-0">From 500+ happy clients in {loc}</p></div>
                </div>
            </div>
            <div class="col-lg-6 order-1 order-lg-2">
                <img src="{hero_img}" class="img-fluid img-float" alt="{name} hero">
            </div>
        </div>
    </div>
</section>

<!-- 3. Problem/Challenge -->
<section class="sec bg-bg" id="problem">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">The Challenge with {label_l}</h2>
        <p class="lead text-muted mb-5 max-w-2xl mx-auto">Too many providers in {loc} overpromise and underdeliver. Hidden fees, missed deadlines, and poor communication cause unnecessary stress.</p>
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="{box_cls} border-0 bg-alt shadow-none text-start">
                    <ul class="list-unstyled mb-0 fs-5">
                        <li class="mb-3"><i class="bi bi-x-circle text-danger me-2"></i> Unpredictable pricing that balloons mid-project.</li>
                        <li class="mb-3"><i class="bi bi-x-circle text-danger me-2"></i> Contractors who show up late or not at all.</li>
                        <li><i class="bi bi-x-circle text-danger me-2"></i> Poor quality workmanship that requires fixing later.</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 4. Solution/Mission -->
<section class="sec bg-primary text-white" id="solution">
    <div class="container">
        <div class="row align-items-center g-5">
            <div class="col-lg-6">
                <img src="{work_img}" class="img-fluid rounded-4 shadow-lg" alt="Solution">
            </div>
            <div class="col-lg-6">
                <h2 class="display-5 fw-bold mb-4 text-white">Our Mission</h2>
                <p class="fs-4 mb-4 text-white-50">We started {name} to bring transparency, reliability, and excellence back to {label_l} in {loc}.</p>
                <p class="mb-0 text-white-50">We provide clear written quotes, stick to our timelines, and guarantee our work. Your peace of mind is our top priority.</p>
            </div>
        </div>
    </div>
</section>

<!-- 5. Features -->
<section class="sec bg-alt" id="features">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">Why choose {name}?</h2>
        <p class="lead text-muted mb-5">We bring expertise, reliability, and precision to every project.</p>
        <div class="row g-4">
            <div class="col-md-4"><div class="{box_cls}"><i class="bi bi-shield-check text-primary display-4 mb-3 d-block"></i><h4 class="h5 fw-bold text-text">Fully Certified</h4><p class="text-muted mb-0">Our team holds all required industry certifications.</p></div></div>
            <div class="col-md-4"><div class="{box_cls}"><i class="bi bi-clock-history text-primary display-4 mb-3 d-block"></i><h4 class="h5 fw-bold text-text">On-Time Delivery</h4><p class="text-muted mb-0">We respect your schedule and always deliver on time.</p></div></div>
            <div class="col-md-4"><div class="{box_cls}"><i class="bi bi-star text-primary display-4 mb-3 d-block"></i><h4 class="h5 fw-bold text-text">Quality Guaranteed</h4><p class="text-muted mb-0">We don't leave until you are 100% satisfied.</p></div></div>
        </div>
    </div>
</section>

<!-- 6. Services -->
<section class="sec bg-bg" id="services">
    <div class="container">
        <div class="text-center mb-5">
            <h2 class="section-title {h2c} mx-auto">Our Services in {loc}</h2>
            <p class="lead text-muted">Comprehensive {label_l} solutions tailored for you.</p>
        </div>
        <div class="row g-4">{svcs_html}</div>
    </div>
</section>

<!-- 7. Stats -->
<section class="sec bg-alt py-5 border-top border-bottom" id="stats">
    <div class="container py-4">
        <div class="row g-4 text-center">
            <div class="col-6 col-md-3"><h3 class="display-4 fw-bold text-primary mb-1">15+</h3><p class="text-muted fw-bold text-uppercase mb-0">Years Exp</p></div>
            <div class="col-6 col-md-3"><h3 class="display-4 fw-bold text-primary mb-1">2.4k</h3><p class="text-muted fw-bold text-uppercase mb-0">Projects</p></div>
            <div class="col-6 col-md-3"><h3 class="display-4 fw-bold text-primary mb-1">98%</h3><p class="text-muted fw-bold text-uppercase mb-0">Recommend</p></div>
            <div class="col-6 col-md-3"><h3 class="display-4 fw-bold text-primary mb-1">24/7</h3><p class="text-muted fw-bold text-uppercase mb-0">Support</p></div>
        </div>
    </div>
</section>

<!-- 8. Testimonials -->
<section class="sec bg-bg" id="reviews">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">Client Stories</h2>
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="{box_cls} text-center">
                    <div class="text-warning fs-3 mb-3"><i class="bi bi-star-fill"></i><i class="bi bi-star-fill"></i><i class="bi bi-star-fill"></i><i class="bi bi-star-fill"></i><i class="bi bi-star-fill"></i></div>
                    <p class="fs-4 text-text fst-italic mb-4">"Absolutely brilliant service. The team from {name} arrived on time, were extremely polite, and the final result exceeded our expectations. Highly recommended to anyone in {loc}!"</p>
                    <h5 class="fw-bold text-text mb-0">Sarah Jenkins</h5>
                    <p class="text-muted small">Homeowner in {loc}</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 9. Pricing -->
<section class="sec bg-alt" id="pricing">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">Transparent Pricing</h2>
        <p class="lead text-muted mb-5">No hidden fees, just straightforward options.</p>
        <div class="row g-4 justify-content-center">
            <div class="col-md-4"><div class="{box_cls}"><h4 class="fw-bold text-text">Standard Assessment</h4><h3 class="display-5 fw-bold text-primary my-3">£99</h3><p class="text-muted mb-4">Full inspection and written quote.</p><a href="#contact" class="btn btn-outline-primary w-100 rounded-pill py-2">Book Now</a></div></div>
            <div class="col-md-4"><div class="{box_cls} border-primary shadow"><div class="badge bg-primary rounded-pill mb-3">Most Popular</div><h4 class="fw-bold text-text">Full Service</h4><h3 class="display-5 fw-bold text-primary my-3">£249</h3><p class="text-muted mb-4">Comprehensive delivery of {label_l}.</p><a href="#contact" class="btn btn-primary w-100 rounded-pill py-2 text-white">Book Now</a></div></div>
        </div>
    </div>
</section>

<!-- 10. Team -->
<section class="sec bg-bg" id="team">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">Meet the Experts</h2>
        <div class="row g-4 justify-content-center mt-4">
            <div class="col-6 col-md-3"><img src="{team_img}" class="team-img mb-3"><h5 class="fw-bold text-text mb-1">David S.</h5><p class="text-muted small">Lead Specialist</p></div>
            <div class="col-6 col-md-3"><img src="{hero_img}" class="team-img mb-3"><h5 class="fw-bold text-text mb-1">Emma T.</h5><p class="text-muted small">Operations Manager</p></div>
        </div>
    </div>
</section>

<!-- 11. FAQ -->
<section class="sec bg-alt" id="faq">
    <div class="container">
        <div class="text-center mb-5"><h2 class="section-title {h2c} mx-auto">Frequently Asked Questions</h2></div>
        <div class="row justify-content-center">
            <div class="col-lg-8">
                <div class="accordion" id="faqAccordion">
                  <div class="accordion-item border-0 mb-3 rounded-3 overflow-hidden shadow-sm"><h2 class="accordion-header"><button class="accordion-button fw-bold py-4" type="button" data-bs-toggle="collapse" data-bs-target="#q1">Do you operate outside of {loc}?</button></h2><div id="q1" class="accordion-collapse collapse show" data-bs-parent="#faqAccordion"><div class="accordion-body bg-card text-muted">We primarily serve {loc} and immediate surrounding areas to ensure rapid response times.</div></div></div>
                  <div class="accordion-item border-0 mb-3 rounded-3 overflow-hidden shadow-sm"><h2 class="accordion-header"><button class="accordion-button collapsed fw-bold py-4" type="button" data-bs-toggle="collapse" data-bs-target="#q2">Are your quotes free?</button></h2><div id="q2" class="accordion-collapse collapse" data-bs-parent="#faqAccordion"><div class="accordion-body bg-card text-muted">Yes, we provide free, no-obligation written estimates before any work begins.</div></div></div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 12. Gallery -->
<section class="sec bg-bg" id="gallery">
    <div class="container text-center">
        <h2 class="section-title {h2c} mx-auto">Our Recent Work</h2>
        <div class="row g-4 mt-2">
            <div class="col-md-4"><img src="{work_img}" class="img-fluid rounded-4 shadow-sm" alt="Gallery"></div>
            <div class="col-md-4"><img src="{hero_img}" class="img-fluid rounded-4 shadow-sm" alt="Gallery"></div>
            <div class="col-md-4"><img src="{team_img}" class="img-fluid rounded-4 shadow-sm" alt="Gallery"></div>
        </div>
    </div>
</section>

<!-- 13. CTA -->
<section class="sec bg-primary text-white text-center" id="cta">
    <div class="container">
        <h2 class="display-4 fw-bold mb-4 text-white">Ready to transform your {label_l}?</h2>
        <p class="lead text-white-50 mb-5 max-w-2xl mx-auto">Join hundreds of satisfied customers in {loc}.</p>
        <a href="#contact" class="btn btn-light btn-lg rounded-pill px-5 py-3 fw-bold text-primary shadow">Contact Us Today</a>
    </div>
</section>
"""

    # -------------------------------------------------------------------------
    # LAYOUT 1: Glassmorphism (12 Sections)
    # -------------------------------------------------------------------------
    elif vi == 1:
        svcs_html = "".join([f'<div class="col-md-6 col-lg-4"><div class="{box_cls} text-center"><div class="d-inline-block p-3 rounded-circle bg-primary bg-opacity-10 mb-4"><i class="bi bi-lightning-charge text-primary fs-3"></i></div><h3 class="h4 fw-bold text-text mb-3">{_e(s["title"])}</h3><p class="text-muted mb-0">{_e(s["desc"])}</p></div></div>' for s in svcs_raw[:6]])
        body_html = f"""
<section class="hero hero-divi" id="hero">
    <div class="container h-100 position-relative z-2">
        <div class="row h-100 align-items-center justify-content-center text-center">
            <div class="col-lg-10 pt-5 mt-5">
                <span class="badge bg-primary bg-opacity-10 text-primary border border-primary px-3 py-2 rounded-pill mb-4">Premium {label_l} in {loc}</span>
                <h1 class="{h1c}"><span class="text-gradient">{name}</span><br>{label}</h1>
                <p class="{lc} mx-auto mt-4" style="max-width: 600px;">{pitch}</p>
                <div class="d-flex flex-column flex-sm-row gap-3 justify-content-center mt-5">
                    <a href="#contact" class="{cta}">Book Consultation</a>
                    <a href="#services" class="btn btn-outline-light btn-lg rounded-pill px-5 py-3 fw-bold text-text bg-card border-secondary">View Services</a>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 3. Problem/Solution Combined -->
<section class="sec bg-bg" id="about">
    <div class="container">
        <div class="row g-5 align-items-center">
            <div class="col-lg-6">
                <div class="position-relative">
                    <img src="{hero_img}" class="img-fluid glow-img w-100" style="height:500px; object-fit:cover;" alt="{name}">
                    <div class="position-absolute bottom-0 end-0 p-4 bg-primary text-white rounded-start-4 shadow-lg mb-4">
                        <h4 class="fw-bold mb-0 text-white">#1 Rated</h4>
                        <p class="mb-0 text-white-50">in {loc}</p>
                    </div>
                </div>
            </div>
            <div class="col-lg-6 ps-lg-5">
                <p class="text-primary fw-bold tracking-widest text-uppercase mb-2">The Difference</p>
                <h2 class="{h2c}">Setting a new standard for {label_l}.</h2>
                <p class="text-muted fs-5 mb-5">Tired of unpredictable contractors and hidden fees? We built {name} to offer a transparent, high-end experience from start to finish.</p>
                <div class="d-flex align-items-start mb-4">
                    <div class="bg-primary bg-opacity-10 p-3 rounded-3 me-4"><i class="bi bi-shield-check text-primary fs-4"></i></div>
                    <div><h4 class="h5 fw-bold text-text">Premium Quality</h4><p class="text-muted mb-0">We use only the highest grade materials and proven techniques.</p></div>
                </div>
                <div class="d-flex align-items-start">
                    <div class="bg-primary bg-opacity-10 p-3 rounded-3 me-4"><i class="bi bi-people text-primary fs-4"></i></div>
                    <div><h4 class="h5 fw-bold text-text">Expert Team</h4><p class="text-muted mb-0">Our specialists have decades of combined experience in {loc}.</p></div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 5. Features Grid -->
<section class="sec bg-alt" id="features">
    <div class="container">
        <div class="text-center mb-5">
            <h2 class="{h2c}">Everything you need.</h2>
        </div>
        <div class="row g-4">
            <div class="col-md-4"><div class="{box_cls}"><h3 class="h1 fw-bold text-primary opacity-50 mb-3">01</h3><h4 class="h5 fw-bold text-text">Consultation</h4><p class="text-muted">In-depth discussion of your needs.</p></div></div>
            <div class="col-md-4"><div class="{box_cls}"><h3 class="h1 fw-bold text-primary opacity-50 mb-3">02</h3><h4 class="h5 fw-bold text-text">Execution</h4><p class="text-muted">Flawless delivery by experts.</p></div></div>
            <div class="col-md-4"><div class="{box_cls}"><h3 class="h1 fw-bold text-primary opacity-50 mb-3">03</h3><h4 class="h5 fw-bold text-text">Support</h4><p class="text-muted">Ongoing maintenance and care.</p></div></div>
        </div>
    </div>
</section>

<!-- 6. Services -->
<section class="sec bg-bg" id="services">
    <div class="container">
        <div class="row justify-content-center text-center mb-5">
            <div class="col-lg-8">
                <h2 class="{h2c}">Specialised Services</h2>
                <p class="lead text-muted">Discover how {name} can help transform your ideas into reality.</p>
            </div>
        </div>
        <div class="row g-4">{svcs_html}</div>
    </div>
</section>

<!-- 7. Stats -->
<section class="sec bg-primary" id="stats">
    <div class="container text-center">
        <div class="row g-4 justify-content-center">
            <div class="col-sm-6 col-md-3"><h3 class="display-4 fw-bold text-white mb-2">2k+</h3><p class="text-white-50 text-uppercase tracking-wider mb-0 small fw-bold">Happy Clients</p></div>
            <div class="col-sm-6 col-md-3"><h3 class="display-4 fw-bold text-white mb-2">15</h3><p class="text-white-50 text-uppercase tracking-wider mb-0 small fw-bold">Years Active</p></div>
            <div class="col-sm-6 col-md-3"><h3 class="display-4 fw-bold text-white mb-2">100%</h3><p class="text-white-50 text-uppercase tracking-wider mb-0 small fw-bold">Satisfaction</p></div>
        </div>
    </div>
</section>

<!-- 8. Testimonials -->
<section class="sec bg-alt" id="reviews">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-lg-8 text-center">
                <h2 class="{h2c} mb-5">What Clients Say</h2>
                <div class="glass-card text-center p-5">
                    <i class="bi bi-quote display-1 text-primary opacity-25"></i>
                    <p class="fs-4 text-text mb-4">"The attention to detail and professionalism shown by the team was outstanding. Best {label_l} service in {loc} without a doubt."</p>
                    <h6 class="fw-bold text-text text-uppercase tracking-widest m-0">Michael Chen</h6>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 9. Pricing -->
<section class="sec bg-bg" id="pricing">
    <div class="container text-center">
        <h2 class="{h2c} mb-5">Clear Pricing</h2>
        <div class="row g-4 justify-content-center">
            <div class="col-md-4"><div class="{box_cls} d-flex flex-column"><h4 class="text-text fw-bold">Essential</h4><h2 class="display-4 fw-bold text-primary my-4">£149</h2><p class="text-muted flex-grow-1">Perfect for small residential jobs.</p><a href="#contact" class="btn btn-outline-primary rounded-pill py-3 w-100 mt-4">Choose Plan</a></div></div>
            <div class="col-md-4"><div class="{box_cls} pricing-featured d-flex flex-column"><h4 class="text-text fw-bold">Premium</h4><h2 class="display-4 fw-bold text-primary my-4">£299</h2><p class="text-muted flex-grow-1">Full service commercial grade delivery.</p><a href="#contact" class="btn btn-primary text-white rounded-pill py-3 w-100 mt-4">Choose Plan</a></div></div>
        </div>
    </div>
</section>

<!-- 10. Team -->
<section class="sec bg-alt" id="team">
    <div class="container text-center">
        <h2 class="{h2c} mb-5">The Minds Behind {name}</h2>
        <div class="row g-5 justify-content-center mt-4">
            <div class="col-sm-6 col-md-4">
                <div class="{box_cls} text-center pt-0">
                    <img src="{team_img}" class="team-img mb-5 shadow">
                    <h5 class="fw-bold text-text mb-1">Sarah K.</h5>
                    <p class="text-primary small text-uppercase tracking-widest fw-bold">Founder</p>
                </div>
            </div>
            <div class="col-sm-6 col-md-4">
                <div class="{box_cls} text-center pt-0">
                    <img src="{hero_img}" class="team-img mb-5 shadow">
                    <h5 class="fw-bold text-text mb-1">James L.</h5>
                    <p class="text-primary small text-uppercase tracking-widest fw-bold">Director</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 11. FAQ -->
<section class="sec bg-bg" id="faq">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-lg-8">
                <h2 class="{h2c} text-center mb-5">Questions?</h2>
                <div class="accordion" id="faqDivi">
                    <div class="accordion-item bg-transparent border-bottom border-secondary mb-3"><h2 class="accordion-header"><button class="accordion-button bg-transparent text-text fw-bold fs-5 shadow-none" type="button" data-bs-toggle="collapse" data-bs-target="#q1">Is there a warranty?</button></h2><div id="q1" class="accordion-collapse collapse show" data-bs-parent="#faqDivi"><div class="accordion-body text-muted border-top border-secondary pt-3">Yes, all our {label_l} work comes with a standard 12-month guarantee.</div></div></div>
                    <div class="accordion-item bg-transparent border-bottom border-secondary mb-3"><h2 class="accordion-header"><button class="accordion-button collapsed bg-transparent text-text fw-bold fs-5 shadow-none" type="button" data-bs-toggle="collapse" data-bs-target="#q2">How fast can you start?</button></h2><div id="q2" class="accordion-collapse collapse" data-bs-parent="#faqDivi"><div class="accordion-body text-muted border-top border-secondary pt-3">We typically begin projects within 48 hours of quote approval.</div></div></div>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 12. Gallery -->
<section class="sec bg-alt" id="gallery">
    <div class="container-fluid px-4">
        <h2 class="{h2c} text-center mb-5">Our Work</h2>
        <div class="row g-4">
            <div class="col-md-6"><img src="{work_img}" class="img-fluid rounded-4 w-100 object-fit-cover shadow" style="height: 400px" alt="Gallery"></div>
            <div class="col-md-6"><img src="{hero_img}" class="img-fluid rounded-4 w-100 object-fit-cover shadow" style="height: 400px" alt="Gallery"></div>
        </div>
    </div>
</section>

<!-- 13. CTA -->
<section class="sec bg-bg" id="cta">
    <div class="container">
        <div class="glass-card text-center p-5 rounded-5 border-primary">
            <h2 class="display-5 fw-bold text-text mb-4">Experience the best {label_l}.</h2>
            <a href="#contact" class="btn btn-primary btn-lg rounded-pill px-5 py-3 fw-bold text-white shadow-lg">Start Your Project</a>
        </div>
    </div>
</section>
"""

    # -------------------------------------------------------------------------
    # LAYOUT 2: Bento Brutal (12 Sections)
    # -------------------------------------------------------------------------
    else:
        svcs_html = "".join([f'<div class="col-md-6"><div class="{box_cls}"><div class="d-flex align-items-center mb-3"><div class="bg-text text-bg rounded-circle d-flex align-items-center justify-content-center me-3 border border-2 border-text" style="width:48px;height:48px;"><i class="bi bi-star-fill"></i></div><h3 class="h4 fw-black text-uppercase mb-0 text-text">{_e(s["title"])}</h3></div><p class="mb-0 fw-medium text-text">{_e(s["desc"])}</p></div></div>' for s in svcs_raw[:4]])
        body_html = f"""
<section class="hero hero-brutal" id="hero">
    <div class="container-fluid px-0 h-100">
        <div class="row g-0 h-100">
            <div class="col-lg-7 d-flex flex-column justify-content-center p-4 p-lg-5">
                <div class="pe-lg-5 pt-5 mt-4">
                    <div class="d-inline-block border border-3 border-text px-3 py-1 fw-bold text-uppercase mb-4 bg-bg text-text shadow-sm">Based in {loc}</div>
                    <h1 class="{h1c}">{name}</h1>
                    <h2 class="display-5 fw-black text-uppercase mb-4 text-primary brutal-heading">{label}</h2>
                    <p class="{lc}">{pitch}</p>
                    <div class="d-flex flex-column flex-sm-row gap-3 mt-5">
                        <a href="#contact" class="{cta}">Get a Quote</a>
                        <a href="#services" class="btn btn-outline-dark btn-lg brutal-btn px-5 py-3 text-uppercase fw-bold rounded-0 border border-3 border-text bg-bg text-text">Services</a>
                    </div>
                </div>
            </div>
            <div class="col-lg-5 d-none d-lg-block">
                <img src="{hero_img}" class="img-fluid brutal-img h-100 w-100 object-fit-cover m-4" style="max-height: 85vh" alt="Hero">
            </div>
        </div>
    </div>
</section>
<div class="marquee">
    <span>{label} in {loc} &bull; {name} &bull; 100% Satisfaction Guaranteed &bull; Quality Workmanship &bull; {label} in {loc} &bull; {name} &bull; 100% Satisfaction Guaranteed</span>
</div>

<!-- 3. Problem -->
<section class="sec bg-bg" id="problem">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">The Problem.</h2></div></div>
        <div class="row">
            <div class="col-12">
                <div class="{box_cls} bg-primary text-white p-4 p-md-5">
                    <h3 class="display-6 fw-black text-uppercase mb-4 text-white">Don't settle for mediocre {label_l}.</h3>
                    <p class="fs-4 fw-bold mb-0 text-white">Late arrivals, messy sites, and blown budgets are the industry standard in {loc}. We refuse to operate that way.</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 4. Solution/Mission -->
<section class="sec bg-alt" id="solution">
    <div class="container">
        <div class="row align-items-center g-5">
            <div class="col-lg-6"><img src="{work_img}" class="img-fluid brutal-img w-100" alt="Work"></div>
            <div class="col-lg-6">
                <h2 class="{h2c}">Our Mission.</h2>
                <p class="fs-4 fw-bold text-text mb-4">To deliver ruthless efficiency and unmatched quality in every project.</p>
                <div class="d-flex gap-2">
                    <span class="badge bg-text text-bg border border-text p-2 fs-6 rounded-0">Honest Quotes</span>
                    <span class="badge bg-text text-bg border border-text p-2 fs-6 rounded-0">On Time</span>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 5. Features -->
<section class="sec bg-bg border-top border-bottom border-text border-3" id="features">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">Our Edge.</h2></div></div>
        <div class="row g-4">
            <div class="col-md-6 col-lg-4"><div class="{box_cls} bg-primary text-white"><h3 class="h2 fw-black text-uppercase mb-3 text-white">01. Speed</h3><p class="fs-5 fw-bold mb-0 text-white">Faster delivery without cutting corners.</p></div></div>
            <div class="col-md-6 col-lg-4"><div class="{box_cls} bg-bg"><h3 class="h2 fw-black text-uppercase mb-3 text-text">02. Power</h3><p class="fs-5 fw-bold mb-0 text-text">Robust solutions designed to last.</p></div></div>
            <div class="col-md-12 col-lg-4"><div class="{box_cls} bg-text text-bg"><h3 class="h2 fw-black text-uppercase mb-3 text-bg">03. Trust</h3><p class="fs-5 fw-bold mb-0 text-bg">Transparent pricing. No hidden fees.</p></div></div>
        </div>
    </div>
</section>

<!-- 6. Services -->
<section class="sec bg-alt" id="services">
    <div class="container">
        <div class="row mb-5 text-center"><div class="col-12"><h2 class="{h2c} d-inline-block bg-primary text-white px-4 py-2">What We Do</h2></div></div>
        <div class="row g-4">{svcs_html}</div>
    </div>
</section>

<!-- 7. Stats -->
<section class="sec bg-bg border-bottom border-text border-3 p-0" id="stats">
    <div class="container-fluid px-0">
        <div class="row g-0 text-center">
            <div class="col-6 col-md-3 border-end border-bottom border-text border-3 p-5"><h3 class="display-3 fw-black text-primary mb-0">15</h3><p class="fw-bold text-uppercase mb-0 text-text">Years</p></div>
            <div class="col-6 col-md-3 border-end border-bottom border-text border-3 p-5"><h3 class="display-3 fw-black text-primary mb-0">2K</h3><p class="fw-bold text-uppercase mb-0 text-text">Clients</p></div>
            <div class="col-6 col-md-3 border-end border-bottom border-text border-3 p-5"><h3 class="display-3 fw-black text-primary mb-0">24</h3><p class="fw-bold text-uppercase mb-0 text-text">Hour Support</p></div>
            <div class="col-6 col-md-3 border-bottom border-text border-3 p-5"><h3 class="display-3 fw-black text-primary mb-0">100</h3><p class="fw-bold text-uppercase mb-0 text-text">Percent</p></div>
        </div>
    </div>
</section>

<!-- 8. Testimonials -->
<section class="sec bg-alt" id="reviews">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">Word on the Street.</h2></div></div>
        <div class="row">
            <div class="col-md-8 offset-md-2">
                <div class="{box_cls} bg-bg">
                    <p class="display-6 fw-bold text-text mb-4">"Absolutely brutal efficiency. They came, they conquered the project, and the final bill was exactly what was quoted."</p>
                    <p class="fw-black text-uppercase text-primary mb-0 fs-5">— Tom Richards, {loc}</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 9. Pricing -->
<section class="sec bg-bg border-top border-bottom border-text border-3" id="pricing">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">Pricing. No BS.</h2></div></div>
        <div class="row g-4">
            <div class="col-md-6"><div class="{box_cls} bg-alt"><h3 class="display-4 fw-black text-text mb-0">£199</h3><p class="fw-bold text-uppercase text-primary mb-4">Starter Fix</p><p class="text-text fw-bold">Get the basics sorted out instantly.</p><a href="#contact" class="btn btn-outline-dark brutal-btn w-100 rounded-0 border-3 border-text text-uppercase fw-bold py-3 mt-3 text-text">Buy Now</a></div></div>
            <div class="col-md-6"><div class="{box_cls} bg-text text-bg"><h3 class="display-4 fw-black text-bg mb-0">£499</h3><p class="fw-bold text-uppercase text-primary mb-4">Pro Overhaul</p><p class="text-bg fw-bold">Complete top-to-bottom service.</p><a href="#contact" class="btn btn-primary brutal-btn w-100 rounded-0 border-3 border-text text-uppercase fw-bold text-white py-3 mt-3">Buy Now</a></div></div>
        </div>
    </div>
</section>

<!-- 10. Team -->
<section class="sec bg-alt" id="team">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">The Crew.</h2></div></div>
        <div class="row g-4">
            <div class="col-6 col-md-3"><div class="bg-bg border border-3 border-text"><img src="{team_img}" class="team-img"><div class="p-3 text-center"><h4 class="fw-black text-uppercase mb-0 text-text">Jake</h4></div></div></div>
            <div class="col-6 col-md-3"><div class="bg-bg border border-3 border-text"><img src="{hero_img}" class="team-img"><div class="p-3 text-center"><h4 class="fw-black text-uppercase mb-0 text-text">Mia</h4></div></div></div>
        </div>
    </div>
</section>

<!-- 11. FAQ -->
<section class="sec bg-bg border-top border-bottom border-text border-3" id="faq">
    <div class="container">
        <div class="row mb-5"><div class="col-12"><h2 class="{h2c}">FAQ.</h2></div></div>
        <div class="row">
            <div class="col-12">
                <div class="{box_cls} mb-3"><h4 class="fw-black text-uppercase text-text">Is there a warranty?</h4><p class="fw-bold text-text mb-0">Yes. 12 months rock solid.</p></div>
                <div class="{box_cls}"><h4 class="fw-black text-uppercase text-text">Do you travel?</h4><p class="fw-bold text-text mb-0">Only within 50 miles of {loc}.</p></div>
            </div>
        </div>
    </div>
</section>

<!-- 12. Gallery -->
<section class="sec bg-primary" id="gallery">
    <div class="container">
        <div class="row align-items-center g-5">
            <div class="col-lg-6">
                <h2 class="display-3 fw-black text-uppercase text-white mb-4">The Proof.</h2>
                <p class="fs-4 fw-bold text-white">We let our results speak for themselves.</p>
            </div>
            <div class="col-lg-6">
                <img src="{work_img}" class="img-fluid brutal-img bg-white" alt="Work">
            </div>
        </div>
    </div>
</section>

<!-- 13. CTA -->
<section class="sec bg-text p-5 border-top border-bottom border-text border-3" id="cta">
    <div class="container text-center">
        <h2 class="display-3 fw-black text-uppercase text-bg mb-4">Time to act.</h2>
        <a href="#contact" class="btn btn-primary btn-lg brutal-btn px-5 py-4 text-uppercase fw-black rounded-0 border border-3 border-text text-white">Contact Us</a>
    </div>
</section>
"""

    # Common Footer & Contact Form
    footer_cls = "bg-card text-text py-5 border-top border-alt" if vi == 0 else ("bg-card text-text py-5 border-top border-alt" if vi == 1 else "bg-bg border-top border-text border-4 py-5")
    
    html_foot = f"""
<!-- 14. Contact Form -->
<section class="sec bg-bg" id="contact">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-lg-8 text-center mb-5">
                <h2 class="{"display-4 fw-bold text-text" if vi!=2 else "display-3 fw-black text-uppercase text-text"} mb-3">Get In Touch</h2>
                <p class="lead text-muted">Fill out the form below and our team will get back to you within 24 hours.</p>
            </div>
        </div>
        <div class="row justify-content-center">
            <div class="col-lg-8">
                <div class="{box_cls}">
                    <form class="row g-4">
                        <div class="col-md-6"><label class="form-label fw-bold text-text">Name</label><input type="text" class="form-control form-control-lg" placeholder="John Doe"></div>
                        <div class="col-md-6"><label class="form-label fw-bold text-text">Email</label><input type="email" class="form-control form-control-lg" placeholder="john@example.com"></div>
                        <div class="col-12"><label class="form-label fw-bold text-text">Message</label><textarea class="form-control form-control-lg" rows="5" placeholder="How can we help?"></textarea></div>
                        <div class="col-12"><button type="button" class="w-100 {cta.replace('btn-lg','py-3')}">Send Message</button></div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- 15. Footer -->
<footer class="{footer_cls}">
    <div class="container">
        <div class="row g-4 mb-4">
            <div class="col-lg-4">
                <h3 class="fw-bold mb-3 text-text">{name}</h3>
                <p class="text-muted">{pitch}</p>
            </div>
            <div class="col-lg-4">
                <h5 class="fw-bold mb-3 text-text">Contact</h5>
                <p class="text-muted mb-1"><i class="bi bi-envelope me-2 text-primary"></i>hello@{email_slug}.com</p>
                <p class="text-muted mb-1"><i class="bi bi-telephone me-2 text-primary"></i>0800 123 4567</p>
                <p class="text-muted"><i class="bi bi-geo-alt me-2 text-primary"></i>{loc}</p>
            </div>
            <div class="col-lg-4">
                <h5 class="fw-bold mb-3 text-text">Follow Us</h5>
                <div class="d-flex gap-3">
                    <a href="#" class="text-muted fs-4"><i class="bi bi-facebook"></i></a>
                    <a href="#" class="text-muted fs-4"><i class="bi bi-instagram"></i></a>
                    <a href="#" class="text-muted fs-4"><i class="bi bi-twitter-x"></i></a>
                </div>
            </div>
        </div>
        <hr class="border-alt mb-4">
        <div class="text-center text-muted small">
            &copy; 2026 {name}. All rights reserved. Design Variation {vi+1} of 3.
        </div>
    </div>
</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
    
    return html_head + body_html + html_foot
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
        
        # Initialize site_pages with index.html as a starting point
        cur.execute("""INSERT INTO site_pages (site_slug,filename,html_content)
            VALUES (%s,'index.html',%s) ON CONFLICT (site_slug,filename) DO UPDATE SET html_content=EXCLUDED.html_content""",
            (slug, row['html_content']))
            
        cur.execute("UPDATE sites SET status='COMPLETED' WHERE slug=%s", (slug,))
        conn.commit()
        cur.close(); conn.close()
        base = request.host_url.rstrip('/')
        return jsonify({"success":True,"previewUrl":f"{base}/s/{slug}","downloadUrl":f"{base}/download/{slug}","html_content":row['html_content']})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

# ── Save site ─────────────────────────────────────────────────────────────────
@app.route('/api/save-site', methods=['POST', 'OPTIONS'])
def save_site():
    if request.method == 'OPTIONS':
        return '', 204
    data  = request.get_json() or {}
    slug  = data.get('slug')
    pages = data.get('pages') # dict of { filename: html }
    if not slug or not pages:
        return jsonify({"success": False, "message": "slug and pages are required"}), 400
    try:
        conn = get_db()
        cur  = conn.cursor()
        
        # Save each page
        for filename, html in pages.items():
            cur.execute("""
                INSERT INTO site_pages (site_slug, filename, html_content)
                VALUES (%s, %s, %s)
                ON CONFLICT (site_slug, filename) DO UPDATE SET html_content=EXCLUDED.html_content
            """, (slug, filename, html))
            
            # Keep index.html synchronized with final_sites for backwards compatibility
            if filename == 'index.html':
                cur.execute("""
                    INSERT INTO final_sites (site_slug, html_content)
                    VALUES (%s, %s)
                    ON CONFLICT (site_slug) DO UPDATE SET html_content=EXCLUDED.html_content
                """, (slug, html))
                
        cur.execute("UPDATE sites SET status='COMPLETED' WHERE slug=%s", (slug,))
        conn.commit()
        cur.close(); conn.close()
        
        base = request.host_url.rstrip('/')
        return jsonify({
            "success": True, 
            "previewUrl": f"{base}/s/{slug}", 
            "downloadUrl": f"{base}/download/{slug}"
        })
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

# ── Final site page ───────────────────────────────────────────────────────────
@app.route('/s/<slug>/<path:filename>')
def show_site_page(slug, filename):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM site_pages WHERE site_slug=%s AND filename=%s", (slug, filename))
        row = cur.fetchone()
        conn.close()
        if row: return html_r(row[0])
        
        # Fallback to index.html from final_sites if filename is index.html
        if filename == 'index.html':
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
            row = cur.fetchone()
            conn.close()
            if row: return html_r(row[0])
            
        return html_r("<h1>Page not found</h1>", 404)
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

# ── Download ZIP ──────────────────────────────────────────────────────────────
@app.route('/download/<slug>')
def download(slug):
    try:
        conn = get_db()
        cur  = conn.cursor()
        
        # Try to get all pages from site_pages
        cur.execute("SELECT filename, html_content FROM site_pages WHERE site_slug=%s", (slug,))
        rows = cur.fetchall()
        
        # Fallback to final_sites if no pages found
        if not rows:
            cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
            row = cur.fetchone()
            if row:
                rows = [('index.html', row[0])]
                
        conn.close()
        
        if not rows: return html_r("<h1>Not found</h1>", 404)
        
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, html in rows:
                zf.writestr(filename, html.encode('utf-8'))
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
        country = (data.get('country') or request.form.get('country') or '').strip()
        traffic = (data.get('traffic') or request.form.get('traffic') or '').strip()
        audience = (data.get('audience') or request.form.get('audience') or '').strip()
        plan = (data.get('plan') or request.form.get('plan') or '').strip()

        if not name or not email or not website or not country or not traffic or not audience or not plan:
            return jsonify({"success": False, "message": "Please fill in all required fields."}), 400

        _lazy_init_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO affiliate_applications (name, email, website, country, monthly_traffic, audience, promotion_plan)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (name, email, website, country, traffic, audience, plan),
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