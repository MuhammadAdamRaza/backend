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
#  AI PROMPT  — 3 distinct design briefs
# ────────────────────────────────────────────────

def build_prompt(data, variation_index):
    name     = data.get('businessName') or data.get('business_name', 'My Business')
    btype    = data.get('businessType') or data.get('business_type', 'business')
    location = data.get('location', 'London')
    services = data.get('services', 'Professional Services')

    # Force structural variety and high content density
    styles = [
        "Modern Glassmorphism with deep blue/purple gradients and floating cards.",
        "Minimalist Corporate with clean white space, sharp lines, and royal blue accents.",
        "Creative & Bold with vibrant colors, large typography, and asymmetric layouts."
    ]
    style = styles[variation_index % 3]

    prompt = f"""
Generate a COMPLETELY FINISHED, professional, and full-length landing page for a business.
Target Business: {name} ({btype})
Location: {loc}
Services to highlight: {services}
Design Style: {style}

CRITICAL STRUCTURAL REQUIREMENTS:
1.  You MUST include at least 7-8 distinct sections:
    -   Navigation (Sticky, transparent to solid on scroll)
    -   Hero (Huge typography, dual buttons, background pattern)
    -   Features Grid (3-4 cards with icons)
    -   Detailed Services Section (Deep descriptions, not just titles)
    -   'How It Works' Process Section (Step 1, 2, 3)
    -   Testimonials Section (3 realistic reviews)
    -   FAQ Section (At least 4 questions/answers)
    -   Pricing or Lead Generation Form Card
    -   Large, Multi-column Footer

2.  CONTENT QUALITY:
    -   Write LONG, professional copy. Do NOT use short placeholders.
    -   Explain WHY this business is the best in {loc}.
    -   Use premium Google Fonts (like 'Plus Jakarta Sans' or 'Inter').
    -   Include smooth hover effects and CSS animations.

3.  TECHNICAL:
    -   Return ONLY the raw HTML/CSS code.
    -   Use Bootstrap 5.3 CDN for the layout.
    -   Ensure all images use high-quality Unsplash URLs (e.g., https://images.unsplash.com/photo-...).
    -   Ensure the code is at least 6,000+ characters long.
    """
    return prompt

# ────────────────────────────────────────────────
#  GENERATE HTML via Gemini
# ────────────────────────────────────────────────

def generate_html(data, variation_index):
    """Bypasses AI and uses the high-quality professional template system directly."""
    print(f"  [{variation_index}] Generating Premium Professional Template...")
    return get_fallback_html(data, variation_index)

def get_fallback_html(data, variation_index):
    """Generates a premium, full-length professional template with 10+ sections."""
    name = data.get('businessName') or data.get('business_name') or "Our Business"
    industry = data.get('businessType') or "Services"
    location = data.get('location') or "Local Area"
    services_raw = data.get('services') or ""
    services = services_raw.split(',') if isinstance(services_raw, str) else ["Quality Service", "Expert Solutions", "24/7 Support"]
    
    themes = [
        {"bg": "#0f172a", "accent": "#3b82f6", "card": "#1e293b", "text": "#fff", "light": "rgba(255,255,255,0.05)"},
        {"bg": "#ffffff", "accent": "#2563eb", "card": "#f8f9fa", "text": "#1e293b", "light": "#f1f5f9"},
        {"bg": "#1e1b4b", "accent": "#818cf8", "card": "#312e81", "text": "#fff", "light": "rgba(255,255,255,0.03)"}
    ]
    t = themes[variation_index % 3]
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} | Premium {industry} in {location}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --accent: {t['accent']}; }}
        body {{ font-family: 'Plus Jakarta Sans', sans-serif; background: {t['bg']}; color: {t['text']}; line-height: 1.7; }}
        .navbar {{ padding: 20px 0; background: {t['bg']}; }}
        .hero {{ padding: 140px 0; background: radial-gradient(circle at 80% 20%, var(--accent), transparent 40%); }}
        .section-padding {{ padding: 100px 0; }}
        .btn-primary {{ background: var(--accent); border: none; padding: 18px 40px; border-radius: 14px; font-weight: 700; }}
        .card {{ background: {t['card']}; border: none; border-radius: 24px; padding: 40px; height: 100%; color: inherit; transition: 0.3s; }}
        .card:hover {{ transform: translateY(-10px); }}
        .icon-box {{ width: 64px; height: 64px; background: var(--accent); border-radius: 16px; display: flex; align-items: center; justify-content: center; color: white; font-size: 24px; margin-bottom: 25px; }}
        .step-num {{ font-size: 4rem; font-weight: 800; opacity: 0.1; line-height: 1; }}
        .blog-card {{ background: {t['light']}; border-radius: 20px; overflow: hidden; }}
        .footer {{ padding: 80px 0; border-top: 1px solid rgba(128,128,128,0.1); }}
    </style>
</head>
<body>
    <nav class="navbar sticky-top">
        <div class="container">
            <a class="navbar-brand fw-bold fs-3 text-inherit" href="#">{name.upper()}</a>
            <button class="btn btn-primary d-none d-md-block">Contact Us</button>
        </div>
    </nav>

    <header class="hero">
        <div class="container text-center text-lg-start">
            <div class="row align-items-center">
                <div class="col-lg-7">
                    <span class="badge bg-primary px-3 py-2 rounded-pill mb-4">#1 Rated {industry} in {location}</span>
                    <h1 class="display-1 fw-bolder mb-4">Mastering {industry} for a Better Tomorrow.</h1>
                    <p class="lead fs-3 mb-5 opacity-75">We provide elite, reliable solutions in {location} that empower your business and simplify your life.</p>
                    <div class="d-flex gap-3 justify-content-center justify-content-lg-start">
                        <button class="btn btn-primary btn-lg">Get Started</button>
                        <button class="btn btn-outline-secondary btn-lg rounded-4">Learn More</button>
                    </div>
                </div>
            </div>
        </div>
    </header>

    <section class="section-padding" style="background: {t['light']};">
        <div class="container text-center">
            <div class="row justify-content-center">
                <div class="col-lg-8">
                    <h2 class="display-4 fw-bold mb-4">The Problem with Traditional {industry}</h2>
                    <p class="fs-4 opacity-75 mb-5">Most services in {location} are slow, expensive, and unreliable. At {name}, we've built a better way to handle your {industry} needs, focusing on speed and quality above all else.</p>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding">
        <div class="container">
            <h2 class="text-center display-4 fw-bold mb-5">Core Features</h2>
            <div class="row g-4">
                <div class="col-md-4">
                    <div class="card">
                        <div class="icon-box">✓</div>
                        <h3>Certified Expertise</h3>
                        <p class="opacity-75">Our team consists of the most highly trained {industry} professionals in {location}.</p>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="icon-box">⚡</div>
                        <h3>Rapid Response</h3>
                        <p class="opacity-75">We value your time. Our workflow is optimized for the fastest turnaround in the industry.</p>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="icon-box">♥</div>
                        <h3>Client First</h3>
                        <p class="opacity-75">Every solution we build at {name} starts with understanding your unique goals.</p>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding" style="background: {t['light']};">
        <div class="container">
            <h2 class="text-center display-4 fw-bold mb-5">How It Works</h2>
            <div class="row g-4">
                <div class="col-md-4">
                    <div class="d-flex gap-3">
                        <span class="step-num">01</span>
                        <div><h3>Consultation</h3><p class="opacity-75">We discuss your specific {industry} requirements in {location}.</p></div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="d-flex gap-3">
                        <span class="step-num">02</span>
                        <div><h3>Implementation</h3><p class="opacity-75">Our experts deploy the custom solution built specifically for {name}.</p></div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="d-flex gap-3">
                        <span class="step-num">03</span>
                        <div><h3>Optimization</h3><p class="opacity-75">We provide ongoing support to ensure long-term success for your project.</p></div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding">
        <div class="container text-center">
            <h2 class="display-4 fw-bold mb-5">What People Say</h2>
            <div class="row g-4">
                <div class="col-md-4">
                    <div class="card">
                        <p class="fs-5 italic opacity-75">"{name} completely changed how we view {industry}. Their team in {location} is second to none!"</p>
                        <h4 class="mt-4">— John Smith</h4>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <p class="fs-5 italic opacity-75">"Professional, fast, and exactly what we needed. Highly recommend for any {industry} work."</p>
                        <h4 class="mt-4">— Sarah Johnson</h4>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <p class="fs-5 italic opacity-75">"The attention to detail is amazing. They are truly the leaders in {location}."</p>
                        <h4 class="mt-4">— Michael Brown</h4>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding" style="background: {t['light']};">
        <div class="container">
            <div class="row align-items-center g-5">
                <div class="col-lg-6">
                    <h2 class="display-3 fw-bold mb-4">Our Mission</h2>
                    <p class="fs-4 opacity-75 mb-4">At {name}, our "Why" is simple: We believe that high-quality {industry} services should be accessible, transparent, and built on trust.</p>
                    <p class="fs-5 opacity-50">Since our founding in {location}, we have been humanizing the brand experience by connecting with our clients on a personal level.</p>
                </div>
                <div class="col-lg-6">
                    <div class="card p-0 overflow-hidden">
                        <img src="https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=800&q=80" class="img-fluid" alt="Our Team">
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding">
        <div class="container">
            <h2 class="text-center display-4 fw-bold mb-5">Resource Library</h2>
            <div class="row g-4">
                <div class="col-md-4">
                    <div class="blog-card p-4">
                        <h4 class="mb-3">Mastering {industry} in 2026</h4>
                        <p class="opacity-75">The latest trends and strategies for success in {location}.</p>
                        <a href="#" class="text-primary fw-bold">Read More &rarr;</a>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="blog-card p-4">
                        <h4 class="mb-3">Why {name} Leads the Market</h4>
                        <p class="opacity-75">A deep dive into our unique workflow and results.</p>
                        <a href="#" class="text-primary fw-bold">Read More &rarr;</a>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="blog-card p-4">
                        <h4 class="mb-3">Avoiding Common Pitfalls</h4>
                        <p class="opacity-75">Expert advice on managing your {industry} projects effectively.</p>
                        <a href="#" class="text-primary fw-bold">Read More &rarr;</a>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding" style="background: {t['light']};">
        <div class="container">
            <h2 class="text-center display-4 fw-bold mb-5">FAQ</h2>
            <div class="row justify-content-center">
                <div class="col-lg-8">
                    <div class="accordion accordion-flush" id="faqAcc">
                        <div class="accordion-item bg-transparent text-inherit border-bottom">
                            <h2 class="accordion-header"><button class="accordion-button bg-transparent text-inherit collapsed py-4 fs-4 fw-bold" type="button" data-bs-toggle="collapse" data-bs-target="#q1">How fast can you start in {location}?</button></h2>
                            <div id="q1" class="accordion-collapse collapse" data-bs-parent="#faqAcc"><div class="accordion-body fs-5 opacity-75">We typically begin work within 24-48 hours of your inquiry.</div></div>
                        </div>
                        <div class="accordion-item bg-transparent text-inherit border-bottom">
                            <h2 class="accordion-header"><button class="accordion-button bg-transparent text-inherit collapsed py-4 fs-4 fw-bold" type="button" data-bs-toggle="collapse" data-bs-target="#q2">What makes {name} different?</button></h2>
                            <div id="q2" class="accordion-collapse collapse" data-bs-parent="#faqAcc"><div class="accordion-body fs-5 opacity-75">Our focus on innovation, transparent pricing, and deep experience in {industry}.</div></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section-padding" id="contact">
        <div class="container">
            <div class="row align-items-center g-5">
                <div class="col-lg-6">
                    <h2 class="display-3 fw-bold mb-4">Ready to elevate your project?</h2>
                    <p class="fs-4 opacity-75 mb-5">Contact our team in {location} today and let's build something incredible together.</p>
                </div>
                <div class="col-lg-6">
                    <div class="card" style="border: 1px solid rgba(128,128,128,0.2);">
                        <form>
                            <div class="mb-4"><input type="text" class="form-control py-3" placeholder="Full Name"></div>
                            <div class="mb-4"><input type="email" class="form-control py-3" placeholder="Email Address"></div>
                            <div class="mb-4"><textarea class="form-control" rows="4" placeholder="How can we help?"></textarea></div>
                            <button class="btn btn-primary w-100 py-3">Send Message</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <footer class="footer">
        <div class="container text-center">
            <h2 class="fw-bold mb-4">{name}</h2>
            <div class="d-flex justify-content-center gap-4 mb-4 opacity-50">
                <a href="#" class="text-inherit">Twitter</a>
                <a href="#" class="text-inherit">Instagram</a>
                <a href="#" class="text-inherit">LinkedIn</a>
            </div>
            <p class="opacity-50">&copy; 2026. All rights reserved. Professional {industry} Solutions in {location}.</p>
        </div>
    </footer>
</body>
</html>
"""

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