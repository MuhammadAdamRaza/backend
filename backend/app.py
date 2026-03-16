import os
import json
import sys
import shutil
import tempfile
import re
import subprocess
import requests
import datetime
import random
import traceback

from flask import Flask, request, jsonify, send_from_directory, render_template_string, send_file
from flask_cors import CORS
import google.generativeai as genai
from openai import OpenAI
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
    "plumber":      ("plumbing,pipes,bathroom,fix",          "💧", "#0ea5e9"),
    "electrician":  ("electrician,wiring,tools,electrical",  "⚡", "#f59e0b"),
    "restaurant":   ("restaurant,food,dining,cuisine",       "🍽️", "#ef4444"),
    "law":          ("law,legal,courtroom,attorney",         "⚖️", "#1e3a5f"),
    "consulting":   ("business,consulting,meeting,office",   "📊", "#6366f1"),
    "fitness":      ("gym,fitness,workout,training",         "💪", "#10b981"),
    "realestate":   ("realestate,house,property,luxury",     "🏠", "#f97316"),
    "agency":       ("design,creative,studio,branding",      "🎨", "#8b5cf6"),
    "shoes":        ("shoes,footwear,fashion,retail",        "👟", "#ec4899"),
    "beauty":       ("beauty,salon,spa,cosmetics",           "💅", "#f43f5e"),
    "medical":      ("medical,clinic,doctor,health",         "🏥", "#06b6d4"),
    "education":    ("education,school,teaching,learning",   "📚", "#84cc16"),
    "tech":         ("technology,software,innovation,tech",  "💻", "#3b82f6"),
    "construction": ("construction,building,architecture",   "🏗️", "#78716c"),
    "cleaning":     ("cleaning,housekeeping,professional",   "✨", "#14b8a6"),
    "photography":  ("photography,camera,studio,portrait",   "📸", "#a855f7"),
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

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
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
        print("Database tables checked/created")
    except Exception as e:
        print(f"DB init error (non-fatal): {e}")
    finally:
        cur.close()
        conn.close()

with app.app_context():
    init_db()

# ────────────────────────────────────────────────
#  AI CLIENTS
# ────────────────────────────────────────────────

openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = "models/gemini-2.0-flash"

model = None
if gemini_key:
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(gemini_model_name)
        print(f"Gemini initialized: {gemini_model_name}")
    except Exception as e:
        print(f"Gemini setup failed: {e}")
        model = None

LAST_AI_ERROR = "No AI errors recorded yet"

# ────────────────────────────────────────────────
#  PATHS
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_ROOT = tempfile.gettempdir()
GENERATED_DIR = os.path.join(TEMP_ROOT, "generated-ai-sites")
os.makedirs(GENERATED_DIR, exist_ok=True)

# ────────────────────────────────────────────────
#  AI GENERATION
# ────────────────────────────────────────────────

def generate_custom_site_html(data, variation_index=0):
    global LAST_AI_ERROR

    if not model and not client:
        LAST_AI_ERROR = "No AI client available (Gemini or OpenAI key missing)"
        return None

    business_name = data.get('businessName') or data.get('business_name', 'My Business')
    business_type = data.get('businessType') or data.get('business_type', 'business')
    location      = data.get('location', 'International')
    services      = data.get('services', '')
    style         = data.get('style', 'modern')
    colors        = data.get('colors', ["#2563eb", "#7c3aed", "#f8fafc"])

    services_list = [s.strip() for s in services.split(',') if s.strip()]
    if not services_list:
        services_list = ["Professional Services", "Expert Solutions", "Quality Results"]

    img_keywords, _, _ = get_category_info(business_type)
    hero_img = f"https://loremflickr.com/1920/1080/{img_keywords}"
    card_img = f"https://loremflickr.com/800/600/{img_keywords}"

    layout_patterns = [
        "Hero split-screen + staggered services grid with floating stats counters",
        "Full-screen parallax hero with glassmorphism service cards in wave layout",
        "Minimal giant typography + bento grid services with hover zoom effects",
        "Diagonal dividers + masonry services gallery with CTA ribbon",
        "Asymmetric hero right-aligned + horizontal scroll service cards",
        "Glassmorphism panels + circular icon tiles + animated gradient background",
        "Centered gradient hero + icon tiles + testimonial carousel",
    ]
    selected_layout = layout_patterns[variation_index % len(layout_patterns)]

    prompt = f"""You are a world-class web designer creating a luxury £75,000+ website.

Create ONE unique, stunning single-file HTML5 landing page:

Business: {business_name}
Type: {business_type}
Location: {location}
Style: {style}
Colors: Primary {colors[0]}, Secondary {colors[1]}, Background {colors[2]}
Services: {', '.join(services_list)}
Layout: {selected_layout}

Image URLs to use (use these EXACT urls):
- Hero: {hero_img}
- Cards: {card_img}

STRICT RULES:
- Return ONLY valid HTML starting with <!DOCTYPE html>
- All CSS in <style>, all JS in <script> — NO external frameworks
- Only Google Fonts + Font Awesome from CDN
- Mobile-first, fully responsive
- Real persuasive copy (no lorem ipsum)
- Industry-specific content for {business_type}
- Sections: Hero, About, Services (show each service from the list), Why Choose Us, Testimonials, Contact/CTA
- At least 3000 characters of code
- Variation #{variation_index + 1} — visually distinct from other variations
- Include smooth scroll, hover effects, and subtle animations
- Add a sticky header with business name and nav links
"""

    try:
        temperature = 0.88 + (variation_index * 0.06)

        if model:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=9200,
                    top_p=0.94,
                    top_k=48
                )
            )
            html = response.text.strip()
        else:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=9000
            )
            html = resp.choices[0].message.content.strip()

        if "```html" in html:
            html = html.split("```html")[1].split("```")[0].strip()
        if not html.startswith("<!DOCTYPE"):
            html = '<!DOCTYPE html>\n' + html

        # Replace any unsplash/placeholder images with category-specific ones
        html = re.sub(
            r'https?://(?:source\.unsplash\.com|picsum\.photos)[^\s"\']*',
            hero_img,
            html
        )

        return html

    except Exception as e:
        LAST_AI_ERROR = f"Variation {variation_index} failed: {str(e)}\n{traceback.format_exc()}"
        print(LAST_AI_ERROR)
        return None

# ────────────────────────────────────────────────
#  CONVERSION WRAPPER — injected around final site
# ────────────────────────────────────────────────

def wrap_with_conversion_banner(html_content, site_data, slug, base_url):
    """Inject a sticky conversion CTA bar + post-preview section into the generated site."""

    business_name = site_data.get('business_name', 'Your Business')
    business_type = site_data.get('business_type', 'business')
    location      = site_data.get('location', '')
    _, emoji, accent = get_category_info(business_type)

    whatsapp_link = "https://wa.me/447700000000?text=I'd+like+to+launch+my+AI+website"
    download_url  = f"{base_url}/download/{slug}"

    banner_html = f"""
<style>
  #ai-cta-banner {{
    position: fixed;
    bottom: 0; left: 0; right: 0;
    z-index: 99999;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: white;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    box-shadow: 0 -8px 40px rgba(0,0,0,0.35);
    font-family: 'Segoe UI', system-ui, sans-serif;
    flex-wrap: wrap;
  }}
  #ai-cta-banner .banner-left {{
    display: flex; align-items: center; gap: 12px;
  }}
  #ai-cta-banner .badge-ai {{
    background: {accent};
    color: white;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  #ai-cta-banner .banner-text {{
    font-size: 14px;
    line-height: 1.4;
  }}
  #ai-cta-banner .banner-text strong {{ font-size: 15px; }}
  #ai-cta-banner .banner-right {{
    display: flex; gap: 10px; flex-wrap: wrap;
  }}
  #ai-cta-banner .btn-cta {{
    padding: 10px 20px;
    border-radius: 30px;
    font-weight: 700;
    font-size: 13px;
    cursor: pointer;
    border: none;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  #ai-cta-banner .btn-cta:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(0,0,0,0.3);
  }}
  #ai-cta-banner .btn-primary-cta {{
    background: linear-gradient(135deg, #22c55e, #16a34a);
    color: white;
  }}
  #ai-cta-banner .btn-secondary-cta {{
    background: rgba(255,255,255,0.12);
    color: white;
    border: 1px solid rgba(255,255,255,0.2) !important;
  }}
  #ai-cta-banner .btn-close-banner {{
    background: transparent;
    border: none;
    color: rgba(255,255,255,0.5);
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
    line-height: 1;
  }}
  body {{ padding-bottom: 80px !important; }}
  @media (max-width: 640px) {{
    #ai-cta-banner {{ padding: 12px 16px; }}
    #ai-cta-banner .banner-text {{ font-size: 12px; }}
  }}
</style>
<div id="ai-cta-banner">
  <div class="banner-left">
    <span class="badge-ai">✨ AI Preview</span>
    <div class="banner-text">
      <strong>{emoji} {business_name} — Your website is ready!</strong><br>
      Our team will finalise &amp; launch it for you — <strong style="color:#4ade80">completely free</strong>
    </div>
  </div>
  <div class="banner-right">
    <a href="{whatsapp_link}" target="_blank" class="btn-cta btn-primary-cta">
      🚀 Launch My Site Free
    </a>
    <a href="{download_url}" class="btn-cta btn-secondary-cta">
      ⬇ Download HTML
    </a>
    <button class="btn-close-banner" onclick="document.getElementById('ai-cta-banner').style.display='none';document.body.style.paddingBottom='0'">✕</button>
  </div>
</div>
"""

    # Inject banner just before </body>
    if "</body>" in html_content:
        return html_content.replace("</body>", f"{banner_html}\n</body>")
    return html_content + banner_html


# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

@app.route('/')
def home():
    return "<h1>AI Website Generator Backend</h1><p>Frontend → /build-with-ai</p>"

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "gemini_model": gemini_model_name if model else "disabled",
        "openai": "active" if client else "disabled",
        "database": "connected" if DATABASE_URL else "missing",
        "last_ai_error": LAST_AI_ERROR[:300]
    })

# ── Pending Placeholder Page ─────────────────────
@app.route('/pending/<slug>')
def pending_page(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()
        conn.close()

        if not site:
            return "<h1>Site not found</h1>", 404

        business_name = site['business_name'] or 'Your Business'
        business_type = site['business_type'] or 'business'
        location      = site['location'] or 'Your City'
        img_keywords, emoji, accent = get_category_info(business_type)
        hero_img      = f"https://loremflickr.com/1400/700/{img_keywords}"
        base_url      = request.host_url.rstrip('/')

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Building {business_name} Website…</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;900&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --accent: {accent};
      --bg: #f0f4ff;
      --card: #fff;
      --text: #0f172a;
      --muted: #64748b;
    }}
    body {{
      font-family: 'Outfit', sans-serif;
      background: var(--bg);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
    }}

    /* ── HERO IMAGE SECTION ───────────────────── */
    .hero-img-section {{
      width: 100%;
      height: 320px;
      position: relative;
      overflow: hidden;
    }}
    .hero-img-section img {{
      width: 100%; height: 100%;
      object-fit: cover;
      filter: brightness(0.72) saturate(1.15);
    }}
    .hero-overlay {{
      position: absolute; inset: 0;
      background: linear-gradient(to bottom, rgba(0,0,0,0.15) 0%, rgba(0,0,0,0.6) 100%);
      display: flex; flex-direction: column;
      align-items: center; justify-content: flex-end;
      padding-bottom: 36px;
    }}
    .hero-overlay h1 {{
      color: #fff;
      font-size: clamp(2rem, 5vw, 3.5rem);
      font-weight: 900;
      letter-spacing: -0.03em;
      text-align: center;
      text-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }}
    .hero-overlay .loc-tag {{
      margin-top: 8px;
      background: rgba(255,255,255,0.18);
      backdrop-filter: blur(8px);
      color: #fff;
      padding: 6px 20px;
      border-radius: 30px;
      font-size: 14px;
      letter-spacing: 0.05em;
      border: 1px solid rgba(255,255,255,0.3);
    }}

    /* ── STATUS CARD ──────────────────────────── */
    .status-card {{
      width: 92%;
      max-width: 680px;
      margin: -48px auto 0;
      background: var(--card);
      border-radius: 28px;
      box-shadow: 0 24px 80px rgba(0,0,0,0.1);
      padding: 48px 44px;
      text-align: center;
      position: relative;
      z-index: 10;
    }}
    .status-emoji {{ font-size: 52px; line-height: 1; margin-bottom: 16px; display: block; }}
    .status-card h2 {{
      font-size: 1.6rem;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 8px;
    }}
    .status-card .subtitle {{
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.6;
      margin-bottom: 32px;
    }}

    /* ── PROGRESS ─────────────────────────────── */
    .progress-wrap {{
      width: 100%;
      background: #e2e8f0;
      border-radius: 99px;
      height: 10px;
      overflow: hidden;
      margin-bottom: 12px;
    }}
    .progress-fill {{
      height: 100%;
      border-radius: 99px;
      background: linear-gradient(90deg, var(--accent), #818cf8);
      background-size: 200% auto;
      animation: progress-anim 2s linear infinite, expand 0.6s ease forwards;
      width: 0%;
    }}
    @keyframes progress-anim {{
      0% {{ background-position: 0% 50%; }}
      100% {{ background-position: 200% 50%; }}
    }}
    @keyframes expand {{
      to {{ width: var(--target-width, 30%); }}
    }}
    .progress-label {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 28px;
      min-height: 20px;
    }}

    /* ── STEPS ────────────────────────────────── */
    .steps {{
      display: flex;
      justify-content: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 36px;
    }}
    .step {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      transition: all 0.4s;
      background: #f1f5f9;
      color: #94a3b8;
    }}
    .step.done {{ background: #dcfce7; color: #16a34a; }}
    .step.active {{ background: #ede9fe; color: #7c3aed; }}
    .step .dot {{ width: 8px; height: 8px; border-radius: 50%; background: currentColor; }}

    /* ── CTA BUTTON ───────────────────────────── */
    .cta-btn {{
      display: inline-block;
      background: linear-gradient(135deg, var(--accent), #818cf8);
      color: white;
      font-weight: 700;
      padding: 16px 40px;
      border-radius: 50px;
      text-decoration: none;
      font-size: 1rem;
      transition: transform 0.25s, box-shadow 0.25s;
      box-shadow: 0 8px 24px rgba(0,0,0,0.15);
      cursor: pointer;
      border: none;
    }}
    .cta-btn:hover {{
      transform: translateY(-3px);
      box-shadow: 0 16px 40px rgba(0,0,0,0.2);
    }}

    /* ── WHY SECTION ──────────────────────────── */
    .why-section {{
      width: 92%;
      max-width: 780px;
      margin: 40px auto 60px;
    }}
    .why-section h3 {{
      text-align: center;
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 8px;
    }}
    .why-section .why-sub {{
      text-align: center;
      color: var(--muted);
      margin-bottom: 28px;
      font-size: 0.95rem;
    }}
    .why-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }}
    .why-card {{
      background: var(--card);
      border-radius: 20px;
      padding: 24px 20px;
      text-align: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    }}
    .why-card .icon {{ font-size: 28px; margin-bottom: 10px; display: block; }}
    .why-card h4 {{ font-size: 0.9rem; font-weight: 700; color: var(--text); margin-bottom: 4px; }}
    .why-card p {{ font-size: 0.82rem; color: var(--muted); line-height: 1.5; }}

    @media (max-width: 600px) {{
      .status-card {{ padding: 32px 24px; }}
    }}
  </style>
</head>
<body>

  <!-- Business-category hero image -->
  <section class="hero-img-section">
    <img src="{hero_img}" alt="{business_name}" onerror="this.src='https://loremflickr.com/1400/700/business,professional'">
    <div class="hero-overlay">
      <h1>{business_name}</h1>
      <span class="loc-tag">{emoji} {business_type.replace('-',' ').title()} &bull; {location}</span>
    </div>
  </section>

  <!-- Status Card -->
  <div class="status-card">
    <span class="status-emoji" id="statusEmoji">🤖</span>
    <h2 id="statusTitle">Your AI website is being crafted…</h2>
    <p class="subtitle" id="statusSubtitle">
      Our AI is designing <strong>3 completely custom layouts</strong> for {business_name}.<br>
      This usually takes 30–60 seconds.
    </p>

    <div class="progress-wrap">
      <div class="progress-fill" id="progressFill" style="--target-width:15%;"></div>
    </div>
    <p class="progress-label" id="progressLabel">Initialising AI design engine…</p>

    <div class="steps">
      <div class="step done" id="step1"><span class="dot"></span> Details Received</div>
      <div class="step active" id="step2"><span class="dot"></span> AI Designing</div>
      <div class="step" id="step3"><span class="dot"></span> Variations Ready</div>
      <div class="step" id="step4"><span class="dot"></span> Choose &amp; Launch</div>
    </div>

    <button class="cta-btn" id="ctaBtn" style="display:none" onclick="window.location='{base_url}/build-with-ai'">
      ✕ Start Over
    </button>
  </div>

  <!-- Why Choose Us Section -->
  <section class="why-section">
    <h3>Why Businesses Love Our AI Builder</h3>
    <p class="why-sub">From AI preview to live website — completely free to start</p>
    <div class="why-grid">
      <div class="why-card">
        <span class="icon">⚡</span>
        <h4>Ready in Minutes</h4>
        <p>AI generates 3 unique designs in under 60 seconds</p>
      </div>
      <div class="why-card">
        <span class="icon">🎨</span>
        <h4>Fully Custom</h4>
        <p>Every site is unique — built around your brand and industry</p>
      </div>
      <div class="why-card">
        <span class="icon">🚀</span>
        <h4>Free Launch</h4>
        <p>Our team finalises and deploys your site at no cost</p>
      </div>
      <div class="why-card">
        <span class="icon">📱</span>
        <h4>Mobile-First</h4>
        <p>Perfectly responsive on every screen size</p>
      </div>
    </div>
  </section>

  <script>
    const API_BASE = '{base_url}';
    const slug = '{slug}';
    let pollCount = 0;

    const steps_map = {{
      'STARTING':          {{ emoji:'🔨', title:'Preparing your canvas…', sub:'Analysing your business details and industry', progress:'20%', label:'Setting up AI generation…', step:2 }},
      'GENERATING_0':      {{ emoji:'✏️', title:'Designing Layout 1 of 3…', sub:'Creating your first unique design concept', progress:'40%', label:'Crafting layout & structure…', step:2 }},
      'GENERATING_1':      {{ emoji:'🖌️', title:'Designing Layout 2 of 3…', sub:'Building your second design variation', progress:'65%', label:'Adding colours and typography…', step:2 }},
      'GENERATING_2':      {{ emoji:'🎨', title:'Designing Layout 3 of 3…', sub:'Finalising your third unique concept', progress:'85%', label:'Polishing the final design…', step:2 }},
      'AWAITING_SELECTION':{{ emoji:'🎉', title:'3 Designs Are Ready!', sub:'Choose your favourite to finalise and launch', progress:'100%', label:'All variations complete!', step:3 }},
      'COMPLETED':         {{ emoji:'✅', title:'Website Live!', sub:'Your website has been finalised', progress:'100%', label:'Redirecting…', step:4 }},
    }};

    function setStep(n) {{
      ['step1','step2','step3','step4'].forEach((id, i) => {{
        const el = document.getElementById(id);
        el.className = 'step' + (i+1 < n ? ' done' : i+1 === n ? ' active' : '');
      }});
    }}

    async function poll() {{
      try {{
        const res  = await fetch(`${{API_BASE}}/api/status/${{slug}}`);
        const data = await res.json();
        const info = steps_map[data.status] || {{ emoji:'⏳', title:'Working…', sub:data.message||'', progress:'50%', label:'Processing…', step:2 }};

        document.getElementById('statusEmoji').textContent   = info.emoji;
        document.getElementById('statusTitle').textContent   = info.title;
        document.getElementById('statusSubtitle').innerHTML  = info.sub;
        document.getElementById('progressFill').style.cssText= `--target-width:${{info.progress}};animation:progress-anim 2s linear infinite,expand 0.6s ease forwards`;
        document.getElementById('progressLabel').textContent = info.label;
        setStep(info.step);

        if (data.status === 'AWAITING_SELECTION') {{
          // Redirect to the selection page (same build-with-ai page, but pass the slug)
          setTimeout(() => {{ window.location = `${{API_BASE}}/select/${{slug}}`; }}, 1200);
          return;
        }}
        if (data.status === 'COMPLETED') {{
          setTimeout(() => {{ window.location = `${{API_BASE}}/s/${{slug}}`; }}, 800);
          return;
        }}
        if (data.status === 'ERROR' || data.status === 'FAILED') {{
          document.getElementById('statusEmoji').textContent  = '❌';
          document.getElementById('statusTitle').textContent  = 'Something went wrong';
          document.getElementById('statusSubtitle').innerHTML = data.message || 'Please try again';
          document.getElementById('ctaBtn').style.display     = 'inline-block';
          document.getElementById('ctaBtn').textContent       = '↩ Try Again';
          return;
        }}

        pollCount++;
        setTimeout(poll, pollCount < 3 ? 2000 : 3500);
      }} catch(e) {{
        setTimeout(poll, 4000);
      }}
    }}

    poll();
  </script>
</body>
</html>"""
        return html
    except Exception as e:
        traceback.print_exc()
        return f"<h1>Error: {str(e)}</h1>", 500


# ── Design Selection Page ────────────────────────
@app.route('/select/<slug>')
def design_selection_page(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()
        cur.execute("SELECT variation_index FROM variations WHERE site_slug = %s ORDER BY variation_index", (slug,))
        variations = cur.fetchall()
        conn.close()

        if not site:
            return "<h1>Site not found</h1>", 404

        business_name = site['business_name'] or 'Your Business'
        _, emoji, accent = get_category_info(site.get('business_type', 'other'))
        base_url = request.host_url.rstrip('/')

        var_cards = ""
        for v in variations:
            idx = v['variation_index']
            var_cards += f"""
            <div class="design-card" data-index="{idx}">
              <div class="card-header">
                <span class="var-badge">Design {idx + 1}</span>
                <span class="var-sub">AI Generated Layout</span>
              </div>
              <div class="iframe-wrap">
                <iframe src="{base_url}/view-design/{slug}/{idx}" loading="lazy"></iframe>
                <div class="iframe-overlay" onclick="chooseDesign('{slug}', {idx})"></div>
              </div>
              <div class="card-footer">
                <button class="btn-select" onclick="chooseDesign('{slug}', {idx})">
                  ✅ Choose This Design
                </button>
                <a href="{base_url}/view-design/{slug}/{idx}" target="_blank" class="btn-preview">
                  👁 Full Preview
                </a>
              </div>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Choose Your Design — {business_name}</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Outfit', sans-serif; background: #f0f4ff; color: #0f172a; }}

    header {{
      position: sticky; top: 0; z-index: 100;
      background: rgba(255,255,255,0.95);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid rgba(0,0,0,0.06);
      padding: 18px 32px;
      display: flex; align-items: center; justify-content: space-between;
    }}
    header h1 {{ font-size: 1.1rem; font-weight: 700; }}
    header .back-btn {{
      text-decoration: none; color: #64748b;
      font-size: 14px; font-weight: 600;
      padding: 8px 16px; border-radius: 20px;
      border: 1px solid #e2e8f0; transition: all 0.2s;
    }}
    header .back-btn:hover {{ background: #f1f5f9; }}

    .hero-section {{
      text-align: center;
      padding: 60px 24px 48px;
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      color: white;
    }}
    .hero-section .tag {{
      display: inline-block;
      background: {accent};
      color: white;
      padding: 6px 18px;
      border-radius: 30px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin-bottom: 20px;
    }}
    .hero-section h2 {{
      font-size: clamp(1.8rem, 4vw, 3rem);
      font-weight: 900;
      letter-spacing: -0.02em;
      margin-bottom: 12px;
    }}
    .hero-section p {{
      font-size: 1.05rem;
      color: rgba(255,255,255,0.7);
      max-width: 500px;
      margin: 0 auto;
    }}

    .designs-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 28px;
      max-width: 1300px;
      margin: 48px auto;
      padding: 0 24px 60px;
    }}

    .design-card {{
      background: white;
      border-radius: 24px;
      overflow: hidden;
      box-shadow: 0 12px 40px rgba(0,0,0,0.08);
      transition: transform 0.3s, box-shadow 0.3s;
    }}
    .design-card:hover {{
      transform: translateY(-8px);
      box-shadow: 0 28px 70px rgba(0,0,0,0.14);
    }}
    .card-header {{
      padding: 18px 22px 14px;
      display: flex; align-items: baseline; gap: 10px;
    }}
    .var-badge {{
      background: {accent};
      color: white;
      font-size: 11px; font-weight: 700;
      padding: 4px 12px; border-radius: 20px;
      text-transform: uppercase; letter-spacing: 0.5px;
    }}
    .var-sub {{ color: #94a3b8; font-size: 13px; }}

    .iframe-wrap {{
      position: relative; width: 100%; height: 480px; overflow: hidden;
    }}
    .iframe-wrap iframe {{
      width: 100%; height: 100%; border: none;
      pointer-events: none;
      transform: scale(0.95);
      transform-origin: top center;
    }}
    .iframe-overlay {{
      position: absolute; inset: 0;
      cursor: pointer;
      background: transparent;
    }}
    .iframe-overlay:hover {{ background: rgba(99,102,241,0.05); }}

    .card-footer {{
      padding: 18px 22px;
      display: flex; gap: 10px;
    }}
    .btn-select {{
      flex: 1;
      background: linear-gradient(135deg, {accent}, #818cf8);
      color: white; border: none;
      padding: 13px 20px; border-radius: 14px;
      font-size: 14px; font-weight: 700;
      cursor: pointer; transition: all 0.25s;
    }}
    .btn-select:hover {{
      transform: translateY(-2px);
      box-shadow: 0 10px 28px rgba(0,0,0,0.2);
    }}
    .btn-preview {{
      background: #f1f5f9; color: #475569;
      padding: 13px 18px; border-radius: 14px;
      text-decoration: none; font-size: 13px; font-weight: 600;
      transition: background 0.2s;
    }}
    .btn-preview:hover {{ background: #e2e8f0; }}

    /* Loading overlay */
    #loadingOverlay {{
      display: none;
      position: fixed; inset: 0;
      background: rgba(15,23,42,0.85);
      backdrop-filter: blur(8px);
      z-index: 9999;
      flex-direction: column;
      align-items: center; justify-content: center;
      color: white;
    }}
    .spinner {{
      width: 64px; height: 64px;
      border: 4px solid rgba(255,255,255,0.15);
      border-top-color: {accent};
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-bottom: 24px;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    #loadingOverlay h3 {{ font-size: 1.5rem; font-weight: 700; }}
    #loadingOverlay p {{ color: rgba(255,255,255,0.6); margin-top: 8px; }}
  </style>
</head>
<body>

  <header>
    <h1>{emoji} {business_name}</h1>
    <a href="{base_url}/build-with-ai" class="back-btn">← Start Over</a>
  </header>

  <div class="hero-section">
    <div class="tag">✨ AI Generation Complete</div>
    <h2>Choose Your Favourite Design</h2>
    <p>Three unique AI-crafted layouts, built specifically for {business_name}. Pick the one you love.</p>
  </div>

  <div class="designs-grid">
    {var_cards}
  </div>

  <div id="loadingOverlay">
    <div class="spinner"></div>
    <h3>Finalising your website…</h3>
    <p>Just a moment while we package everything up</p>
  </div>

  <script>
    async function chooseDesign(slug, index) {{
      document.getElementById('loadingOverlay').style.display = 'flex';
      try {{
        const res  = await fetch('{base_url}/api/select-design', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ slug, designIndex: index }})
        }});
        const data = await res.json();
        if (data.success) {{
          window.location = data.previewUrl;
        }} else {{
          alert('Could not finalise: ' + (data.message || 'Unknown error'));
          document.getElementById('loadingOverlay').style.display = 'none';
        }}
      }} catch(e) {{
        alert('Error: ' + e.message);
        document.getElementById('loadingOverlay').style.display = 'none';
      }}
    }}
  </script>
</body>
</html>"""
        return html
    except Exception as e:
        traceback.print_exc()
        return f"<h1>Error: {str(e)}</h1>", 500


# ── Generate Site (start) ────────────────────────
@app.route('/api/generate-site', methods=['POST'])
def start_generation():
    try:
        data = request.get_json()
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "businessName is required"}), 400

        name_clean = re.sub(r'[^a-z0-9]+', '-', data['businessName'].lower().strip())
        slug = f"{name_clean}-{random.randint(10000, 99999)}"

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
            'Generation queued…'
        ))
        conn.commit()
        cur.close()
        conn.close()

        base_url = request.host_url.rstrip('/')
        return jsonify({
            "success": True,
            "slug": slug,
            "pendingUrl": f"{base_url}/pending/{slug}"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Status / trigger next generation step ────────
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
            if not html_content:
                html_content = "<h1 style='text-align:center;padding:100px'>AI generation failed — please try again</h1>"

            cur.execute("""
                INSERT INTO variations (site_slug, variation_index, html_content)
                VALUES (%s, %s, %s)
            """, (slug, next_variation, html_content))

            new_status = f'GENERATING_{next_variation}' if next_variation < 2 else 'AWAITING_SELECTION'
            cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s",
                        (new_status, f"Design variation {next_variation + 1} created", slug))
            conn.commit()

        cur.execute("SELECT variation_index FROM variations WHERE site_slug = %s ORDER BY variation_index", (slug,))
        variations = [
            {"id": row["variation_index"], "url": f"{base_url}/view-design/{slug}/{row['variation_index']}"}
            for row in cur.fetchall()
        ]

        response = {
            "status": site['status'],
            "message": site['message'],
            "slug": slug,
            "variations": variations
        }

        if site['status'] in ['AWAITING_SELECTION', 'COMPLETED']:
            response["previewUrl"]    = f"{base_url}/s/{slug}"
            response["selectionUrl"]  = f"{base_url}/select/{slug}"

        conn.close()
        return jsonify(response)

    except psycopg2.Error as db_err:
        return jsonify({"status": "DATABASE_ERROR", "message": str(db_err)}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# ── Select design ────────────────────────────────
@app.route('/api/select-design', methods=['POST'])
def choose_design():
    data = request.get_json()
    slug = data.get('slug')
    design_index = data.get('designIndex')

    if not slug or design_index is None:
        return jsonify({"success": False, "message": "Missing slug or designIndex"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT html_content FROM variations
            WHERE site_slug = %s AND variation_index = %s
        """, (slug, int(design_index)))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Design not found"}), 404

        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()

        base_url = request.host_url.rstrip('/')
        final_html = wrap_with_conversion_banner(row['html_content'], dict(site), slug, base_url)

        cur.execute("""
            INSERT INTO final_sites (site_slug, html_content)
            VALUES (%s, %s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content = EXCLUDED.html_content
        """, (slug, final_html))

        cur.execute("UPDATE sites SET status = 'COMPLETED', message = 'Website ready' WHERE slug = %s", (slug,))
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "previewUrl": f"{base_url}/s/{slug}",
            "downloadUrl": f"{base_url}/download/{slug}"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500


# ── Serve final site (with conversion banner) ────
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
        return "<h1>404 – Website not finalised yet</h1>", 404
    except Exception:
        return "<h1>Server error</h1>", 500


# ── View individual variation ────────────────────
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


# ── Download ZIP ─────────────────────────────────
@app.route('/download/<slug>')
def download_zip(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return "<h1>Not found or not finalised</h1>", 404

        from io import BytesIO
        import zipfile
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0])
        buffer.seek(0)
        return send_file(buffer, mimetype="application/zip",
                         as_attachment=True, download_name=f"{slug}_website.zip")
    except Exception as e:
        return f"<h1>Download failed: {str(e)}</h1>", 500


if __name__ == '__main__':
    print("AI Website Builder backend starting…")
    app.run(host='0.0.0.0', port=5000, debug=True)
