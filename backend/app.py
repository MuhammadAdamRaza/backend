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

# Curated Unsplash photo IDs — guaranteed correct category images, no random cats
# Format: (hero_photo_id, card_photo_id, emoji, accent_color)
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
    """Return (hero_url, card_url, emoji, accent) with real Unsplash photos."""
    hero_id, card_id, emoji, accent = get_category_info(business_type)
    hero = f"https://images.unsplash.com/photo-{hero_id}?w=1920&q=80&fit=crop"
    card = f"https://images.unsplash.com/photo-{card_id}?w=800&q=80&fit=crop"
    return hero, card, emoji, accent

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
#  PROMPT BUILDER  — 3 visually distinct designs
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
    svc_lines = "\n".join(f"  - {sv}" for sv in svc_list)

    # 3 completely different design specs
    DESIGNS = [
        # ── Design 1: Dark Bold Hero ──────────────────────────────────────────
        {
            "title": "Dark Bold Hero",
            "font_url": "Montserrat:wght@400;700;900",
            "font_family": "'Montserrat', sans-serif",
            "nav_css": "background:rgba(8,8,8,0.97);backdrop-filter:blur(10px);",
            "nav_text": "color:#ffffff;",
            "logo_style": "color:#fff;font-weight:900;font-size:1.4rem;",
            "hero_css": f"min-height:100vh;background:linear-gradient(rgba(0,0,0,0.60),rgba(0,0,0,0.60)),url('{hero_url}') center/cover no-repeat;display:flex;align-items:center;justify-content:center;text-align:center;padding:100px 24px 60px;",
            "hero_h1": "font-size:clamp(2.8rem,6vw,5rem);font-weight:900;color:#fff;letter-spacing:-2px;line-height:1.05;margin-bottom:20px;",
            "hero_p": "font-size:1.2rem;color:rgba(255,255,255,0.85);max-width:580px;margin:0 auto 36px;",
            "btn1_css": f"background:{p};color:#fff;padding:18px 48px;border-radius:50px;font-weight:700;",
            "btn2_css": "",
            "section_services_bg": "#ffffff",
            "card_css": "background:#fff;border-radius:12px;padding:36px 28px;box-shadow:0 4px 24px rgba(0,0,0,0.08);transition:all 0.3s;",
            "icon_css": f"font-size:2.2rem;color:{p};margin-bottom:16px;display:block;",
            "card_h3_css": "font-size:1.05rem;font-weight:800;color:#0a0a0a;margin-bottom:10px;",
            "why_css": f"background:{p};padding:80px 5%;",
            "cta_css": f"background:linear-gradient(135deg,{p},{s});padding:90px 5%;text-align:center;",
            "footer_css": "background:#0a0a0a;color:rgba(255,255,255,0.55);",
        },
        # ── Design 2: Clean Corporate Split ──────────────────────────────────
        {
            "title": "Clean Corporate",
            "font_url": "Inter:wght@300;400;600;700;800",
            "font_family": "'Inter', sans-serif",
            "nav_css": "background:#ffffff;border-bottom:2px solid #f0f0f0;",
            "nav_text": f"color:{p};",
            "logo_style": f"color:{p};font-weight:800;font-size:1.3rem;",
            "hero_css": f"min-height:88vh;display:grid;grid-template-columns:1fr 1fr;padding-top:72px;",
            "hero_h1": "font-size:clamp(2rem,4vw,3.6rem);font-weight:800;color:#fff;letter-spacing:-1px;line-height:1.1;margin-bottom:20px;",
            "hero_p": "font-size:1rem;color:rgba(255,255,255,0.88);margin-bottom:36px;line-height:1.7;",
            "btn1_css": "background:#fff;color:{P};padding:16px 40px;border-radius:8px;font-weight:700;".replace("{P}", p),
            "btn2_css": "",
            "section_services_bg": "#f9fafb",
            "card_css": "background:#fff;border-radius:10px;padding:32px 24px;border:1px solid #e5e7eb;transition:box-shadow 0.3s;",
            "icon_css": f"font-size:1.9rem;color:{p};margin-bottom:14px;display:block;",
            "card_h3_css": f"font-size:1rem;font-weight:700;color:{p};margin-bottom:8px;",
            "why_css": f"background:{p};padding:80px 5%;",
            "cta_css": "background:#111827;padding:90px 5%;text-align:center;",
            "footer_css": "background:#1f2937;color:rgba(255,255,255,0.55);",
        },
        # ── Design 3: Vibrant Gradient Creative ──────────────────────────────
        {
            "title": "Vibrant Creative",
            "font_url": "Poppins:wght@400;600;700;800;900",
            "font_family": "'Poppins', sans-serif",
            "nav_css": f"background:linear-gradient(135deg,{p},{s});",
            "nav_text": "color:#ffffff;",
            "logo_style": "color:#fff;font-weight:900;font-size:1.4rem;",
            "hero_css": f"min-height:92vh;background:linear-gradient(135deg,{p} 0%,{s} 100%);display:flex;align-items:center;justify-content:center;text-align:center;padding:100px 5% 60px;",
            "hero_h1": "font-size:clamp(2.8rem,6vw,5.5rem);font-weight:900;color:#fff;letter-spacing:-3px;line-height:1.0;margin-bottom:20px;",
            "hero_p": "font-size:1.15rem;color:rgba(255,255,255,0.88);max-width:560px;margin:0 auto 40px;",
            "btn1_css": f"background:#fff;color:{p};padding:18px 44px;border-radius:50px;font-weight:800;margin:0 8px 8px;",
            "btn2_css": "background:transparent;color:#fff;padding:18px 44px;border-radius:50px;font-weight:700;border:2px solid rgba(255,255,255,0.7);margin:0 8px 8px;",
            "section_services_bg": "#ffffff",
            "card_css": f"background:#fff;border-radius:16px;padding:36px 28px;box-shadow:0 8px 32px rgba(0,0,0,0.08);border-top:4px solid {p};transition:transform 0.3s;",
            "icon_css": f"font-size:2rem;width:54px;height:54px;background:linear-gradient(135deg,{p},{s});border-radius:50%;display:inline-flex;align-items:center;justify-content:center;color:#fff;margin-bottom:18px;",
            "card_h3_css": "font-size:1.05rem;font-weight:700;color:#111;margin-bottom:10px;",
            "why_css": f"background:linear-gradient(135deg,{p}18,{s}18);padding:80px 5%;",
            "cta_css": f"background:linear-gradient(135deg,{p},{s});padding:100px 5%;text-align:center;",
            "footer_css": "background:#0f172a;color:rgba(255,255,255,0.55);",
        },
    ]

    d   = DESIGNS[variation_index % 3]
    idx = variation_index % 3

    FA_ICONS = ["star","wrench","shield-halved","rocket","check-circle","award","bolt","gem","crown","handshake","leaf","fire"]

    # Build service cards
    service_cards = "\n".join(
        f'<div class="svc-card">'
        f'<span class="svc-icon"><i class="fa-solid fa-{FA_ICONS[i % len(FA_ICONS)]}"></i></span>'
        f'<h3>{sv}</h3>'
        f'<p>Professional {sv.lower()} delivered by the expert team at {name}. Trusted by clients across {location} for quality results and reliable service.</p>'
        f'</div>'
        for i, sv in enumerate(svc_list)
    )

    # Hero HTML varies per design
    if idx == 1:
        hero_html = (
            f'<section class="hero" id="home">'
            f'<div class="hero-left">'
            f'<h1>Professional {btype.title()}<br>Services in {location}</h1>'
            f'<p>Welcome to {name} — your trusted {btype} partner in {location}. We deliver quality results with integrity and expertise.</p>'
            f'<a href="#contact" class="btn-primary">Get Free Consultation &rarr;</a>'
            f'</div>'
            f'<div class="hero-right" style="background:url(\'{hero_url}\') center/cover no-repeat;"></div>'
            f'</section>'
        )
    else:
        btn2 = f'<a href="#services" class="btn-secondary" style="{d["btn2_css"]}">Explore Services</a>' if d["btn2_css"] else ""
        hero_html = (
            f'<section class="hero" id="home">'
            f'<div>'
            f'<h1>The #1 {btype.title()}<br>in {location}</h1>'
            f'<p>Welcome to {name}. We deliver exceptional {btype} services across {location} — trusted, professional, and always on time.</p>'
            f'<a href="#contact" class="btn-primary" style="{d["btn1_css"]}">Book Free Consultation</a>'
            f'{btn2}'
            f'</div>'
            f'</section>'
        )

    # Why-tile icon color
    why_icon_col = "#fff" if idx in [0,1] else p
    cta_btn_style = f"background:#fff;color:{p};padding:18px 48px;border-radius:50px;font-weight:800;text-decoration:none;display:inline-block;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} | {btype.title()} in {location}</title>
<link href="https://fonts.googleapis.com/css2?family={d['font_url']}&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:{d['font_family']};color:#111;line-height:1.6;background:#fff}}
a{{text-decoration:none}}
img{{max-width:100%}}

/* ─ NAV ─ */
nav{{position:fixed;top:0;width:100%;z-index:1000;{d['nav_css']}padding:0 5%;height:70px;display:flex;align-items:center;justify-content:space-between;}}
.nav-logo{{{d['logo_style']}text-decoration:none;}}
.nav-links a{{text-decoration:none;{d['nav_text']}margin-left:28px;font-size:0.9rem;font-weight:600;opacity:0.9;}}
.nav-links a:hover{{opacity:1}}
.nav-cta{{background:{p};color:#fff !important;padding:10px 22px;border-radius:6px;margin-left:16px;opacity:1 !important;}}
@media(max-width:768px){{.nav-links{{display:none}}}}

/* ─ HERO ─ */
.hero{{{d['hero_css']}}}
.hero h1{{{d['hero_h1']}}}
.hero p{{{d['hero_p']}}}
.hero-left{{background:{p};padding:80px 60px;display:flex;flex-direction:column;justify-content:center;}}
.hero-right{{min-height:500px;}}
.btn-primary{{display:inline-block;{d['btn1_css']}text-decoration:none;transition:all 0.3s;}}
.btn-primary:hover{{transform:translateY(-3px);box-shadow:0 12px 28px rgba(0,0,0,0.2)}}

/* ─ SECTIONS ─ */
.section{{padding:90px 5%;}}
.section h2{{font-size:clamp(1.8rem,3.5vw,2.6rem);font-weight:800;text-align:center;margin-bottom:12px;letter-spacing:-0.5px;}}
.section-sub{{text-align:center;color:#666;font-size:1rem;margin-bottom:48px;max-width:540px;margin-left:auto;margin-right:auto;}}

/* ─ SERVICES ─ */
.svc-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;}}
.svc-card{{{d['card_css']}}}
.svc-card:hover{{transform:translateY(-6px);box-shadow:0 16px 48px rgba(0,0,0,0.12)}}
.svc-icon{{{d['icon_css']}}}
.svc-card h3{{{d['card_h3_css']}}}
.svc-card p{{color:#666;font-size:0.88rem;line-height:1.65;}}

/* ─ ABOUT ─ */
.about-grid{{display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:center;max-width:1100px;margin:0 auto;}}
.about-img{{width:100%;height:420px;object-fit:cover;border-radius:16px;display:block;}}
.about-text h2{{text-align:left;margin-bottom:16px;}}
.about-text p{{color:#555;line-height:1.8;margin-bottom:16px;font-size:0.97rem;}}

/* ─ WHY US ─ */
.why-wrap{{{d['why_css']}}}
.why-wrap h2{{color:#fff;text-align:center;font-size:clamp(1.8rem,3.5vw,2.6rem);font-weight:800;margin-bottom:12px;}}
.why-sub{{text-align:center;color:rgba(255,255,255,0.8);margin-bottom:48px;}}
.why-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:20px;max-width:900px;margin:0 auto;}}
.why-tile{{background:rgba(255,255,255,0.13);border-radius:14px;padding:32px 20px;text-align:center;border:1px solid rgba(255,255,255,0.2);}}
.why-tile i{{font-size:2rem;color:{why_icon_col};margin-bottom:12px;display:block;}}
.why-tile .stat{{font-size:2.2rem;font-weight:900;color:#fff;display:block;line-height:1;}}
.why-tile .lbl{{color:rgba(255,255,255,0.8);font-size:0.85rem;margin-top:6px;display:block;}}

/* ─ TESTIMONIALS ─ */
.testi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;}}
.testi-card{{background:#fff;border-radius:12px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,0.07);border-left:4px solid {p};}}
.stars{{color:#f59e0b;font-size:1rem;margin-bottom:12px;}}
.testi-card blockquote{{color:#444;font-size:0.93rem;line-height:1.72;margin-bottom:14px;font-style:italic;}}
.testi-card cite{{font-weight:700;color:#111;font-size:0.88rem;}}

/* ─ CTA ─ */
.cta-wrap{{{d['cta_css']}}}
.cta-wrap h2{{color:#fff;font-size:clamp(1.8rem,4vw,3rem);font-weight:800;margin-bottom:14px;}}
.cta-wrap p{{color:rgba(255,255,255,0.85);font-size:1.05rem;margin-bottom:36px;max-width:500px;margin-left:auto;margin-right:auto;}}
.cta-btn{{display:inline-block;{cta_btn_style}transition:all 0.3s;}}
.cta-btn:hover{{transform:translateY(-3px);box-shadow:0 12px 32px rgba(0,0,0,0.25)}}

/* ─ CONTACT ─ */
.contact-inner{{max-width:640px;margin:0 auto;}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}}
.contact-inner input,.contact-inner textarea{{width:100%;padding:14px 18px;border:2px solid #e5e7eb;border-radius:10px;font-size:0.95rem;font-family:inherit;outline:none;transition:border-color 0.3s;}}
.contact-inner input:focus,.contact-inner textarea:focus{{border-color:{p};}}
.contact-inner textarea{{min-height:130px;resize:vertical;margin-bottom:16px;}}
.submit-btn{{width:100%;background:{p};color:#fff;padding:16px;border:none;border-radius:10px;font-size:1rem;font-weight:700;cursor:pointer;font-family:inherit;transition:opacity 0.2s;}}
.submit-btn:hover{{opacity:0.9}}

/* ─ FOOTER ─ */
footer{{{d['footer_css']}padding:40px 5%;text-align:center;font-size:0.85rem;}}
footer .fn{{color:#fff;font-weight:700;display:block;margin-bottom:8px;font-size:1rem;}}

/* ─ RESPONSIVE ─ */
@media(max-width:768px){{
  .hero{{grid-template-columns:1fr !important;}}
  .hero-right{{display:none}}
  .hero-left{{padding:100px 24px 60px}}
  .about-grid{{grid-template-columns:1fr}}
  .form-row{{grid-template-columns:1fr}}
  .section{{padding:60px 5%}}
  nav{{padding:0 4%}}
}}
</style>
</head>
<body>

<nav>
  <a href="#home" class="nav-logo">{name}</a>
  <div class="nav-links">
    <a href="#services">Services</a>
    <a href="#about">About</a>
    <a href="#testimonials">Reviews</a>
    <a href="#contact">Contact</a>
    <a href="#contact" class="nav-cta">Get a Quote</a>
  </div>
</nav>

{hero_html}

<section class="section" id="services" style="background:{d['section_services_bg']}">
  <h2>Our Services in {location}</h2>
  <p class="section-sub">From {svc_list[0]} to {svc_list[-1] if len(svc_list)>1 else svc_list[0]} — {name} delivers exceptional results every time.</p>
  <div class="svc-grid">
    {service_cards}
  </div>
</section>

<div class="why-wrap" id="why">
  <h2>Why Choose {name}?</h2>
  <p class="why-sub">Trusted by hundreds of clients across {location}</p>
  <div class="why-grid">
    <div class="why-tile"><i class="fa-solid fa-trophy"></i><span class="stat">500+</span><span class="lbl">Happy Clients</span></div>
    <div class="why-tile"><i class="fa-solid fa-calendar-check"></i><span class="stat">10+</span><span class="lbl">Years Experience</span></div>
    <div class="why-tile"><i class="fa-solid fa-star"></i><span class="stat">4.9★</span><span class="lbl">Avg Rating</span></div>
    <div class="why-tile"><i class="fa-solid fa-headset"></i><span class="stat">24/7</span><span class="lbl">Support</span></div>
  </div>
</div>

<section class="section" id="about" style="background:#f9fafb">
  <div class="about-grid">
    <img class="about-img" src="{card_url}" alt="About {name}" loading="lazy">
    <div class="about-text">
      <h2>About {name}</h2>
      <p>{name} is a leading {btype} business proudly serving {location} and surrounding areas. With over a decade of hands-on experience, we have built a reputation for quality workmanship, honest pricing, and unmatched customer care.</p>
      <p>Whether you need {svc_list[0]} or any of our other specialist services, our skilled team is ready to deliver results that exceed your expectations — on time, every time.</p>
    </div>
  </div>
</section>

<section class="section" id="testimonials">
  <h2>What Clients Say</h2>
  <p class="section-sub">Real reviews from satisfied customers across {location}</p>
  <div class="testi-grid">
    <div class="testi-card"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><blockquote>"Absolutely outstanding service from {name}. Professional, efficient, and the results were incredible. Would recommend to everyone in {location}."</blockquote><cite>— Sarah M., {location}</cite></div>
    <div class="testi-card"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><blockquote>"Used {name} for {svc_list[0]}. Fair pricing, excellent communication, and quality that truly stands out. Will definitely use again."</blockquote><cite>— James T., {location}</cite></div>
    <div class="testi-card"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><blockquote>"From first call to completion, the {name} team made everything stress-free. True professionals who care about their customers."</blockquote><cite>— Priya K., {location}</cite></div>
  </div>
</section>

<div class="cta-wrap">
  <h2>Ready to Work With {name}?</h2>
  <p>Get your free consultation today. Proudly serving {location} and surrounding areas.</p>
  <a href="#contact" class="cta-btn">Book Free Consultation</a>
</div>

<section class="section" id="contact">
  <h2>Get In Touch</h2>
  <p class="section-sub">Send us a message and we will get back to you within 24 hours.</p>
  <div class="contact-inner">
    <div class="form-row">
      <input type="text" placeholder="Your Full Name" required>
      <input type="email" placeholder="Email Address" required>
    </div>
    <div class="form-row">
      <input type="tel" placeholder="Phone Number">
      <input type="text" placeholder="Service Needed">
    </div>
    <textarea placeholder="Tell us about your project..."></textarea>
    <button class="submit-btn" type="button" onclick="this.textContent='Message Sent! We will contact you shortly.';this.style.background='#22c55e'">Send Message &#8594;</button>
  </div>
</section>

<footer>
  <span class="fn">{name}</span>
  {btype.title()} &bull; {location} &bull; &copy; 2025 {name}. All rights reserved.
</footer>

</body>
</html>"""


def generate_html(data, variation_index):
    """
    Returns a complete, professional HTML page.
    The page structure, CSS and content are built directly in Python (build_prompt).
    AI is optionally used only to enhance the copy text.
    """
    global LAST_AI_ERROR
    try:
        html = build_prompt(data, variation_index)
        if html and html.strip().lower().startswith("<!doctype"):
            print(f"  Variation {variation_index} built ({len(html):,} chars)")
            return html
        LAST_AI_ERROR = "build_prompt returned invalid output"
        return None
    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} build error: {e}"
        traceback.print_exc()
        return None

def _generate_html_unused(data, variation_index):
    """Legacy AI-based generation — kept for reference only."""
    global LAST_AI_ERROR, ACTIVE_MODEL

    if not gemini_client and not openai_client:
        LAST_AI_ERROR = "No AI client configured."
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
                            temperature=0.75,
                            max_output_tokens=8192,
                            top_p=0.95,
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
                    temperature=0.75,
                    max_tokens=6000,
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
            futures = {ex.submit(gen, i): i for i in range(3)}
            for future in concurrent.futures.as_completed(futures):
                idx, html = future.result()
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
