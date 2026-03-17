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

# ════════════════════════════════════════════════════════════════
#  CATEGORY IMAGES  (curated Unsplash IDs for HD quality)
# ════════════════════════════════════════════════════════════════

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
    """Get category info based on business type"""
    bt = (business_type or "other").lower().strip()
    for key in CATEGORY_IMAGES:
        if key in bt:
            return CATEGORY_IMAGES[key]
    return CATEGORY_IMAGES["other"]

def get_images(business_type):
    """Get HD quality image URLs"""
    hero_id, card_id, emoji, accent = get_category_info(business_type)
    # HD image optimization: 2560px hero, 1200px cards, 90% quality, retina support
    hero = f"https://images.unsplash.com/photo-{hero_id}?w=2560&q=90&fit=crop&auto=format&dpr=2"
    card = f"https://images.unsplash.com/photo-{card_id}?w=1200&q=90&fit=crop&auto=format&dpr=2"
    return hero, card, emoji, accent

# ════════════════════════════════════════════════════════════════
#  DATABASE SETUP
# ════════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL missing")
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
        # Add unique constraint safely
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'variations_slug_idx_key'
                ) THEN
                    ALTER TABLE variations
                    ADD CONSTRAINT variations_slug_idx_key UNIQUE (site_slug, variation_index);
                END IF;
            END$$;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✓ Database ready")
    except Exception as e:
        print(f"✗ DB init error: {e}")

with app.app_context():
    init_db()

# ════════════════════════════════════════════════════════════════
#  GEMINI AI - Google's Latest Model
# ════════════════════════════════════════════════════════════════

GEMINI_KEY = (
    os.getenv("GEMINI_API_KEY") or
    os.getenv("GOOGLE_API_KEY") or
    os.getenv("GOOGLE_GEMINI_KEY") or ""
)

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
]

gemini_client = None
ACTIVE_MODEL  = "gemini-2.5-flash"
LAST_AI_ERROR = ""

if GEMINI_KEY:
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types
        gemini_client = google_genai.Client(api_key=GEMINI_KEY)
        print(f"✓ Gemini ready — model: {ACTIVE_MODEL}")
    except ImportError:
        print("✗ ERROR: run  pip install google-genai")
    except Exception as e:
        print(f"✗ Gemini error: {e}")
else:
    print("✗ WARNING: GEMINI_API_KEY not set")

# ════════════════════════════════════════════════════════════════
#  ENHANCED AI PROMPT - 3 unique, high-content designs
# ════════════════════════════════════════════════════════════════

def build_prompt(data, variation_index):
    """Build AI prompt for website generation with MUCH better content"""
    name     = data.get('businessName') or data.get('business_name', 'My Business')
    btype    = data.get('businessType') or data.get('business_type', 'business')
    location = data.get('location', 'London')
    services = data.get('services', 'Professional Services')
    colors   = data.get('colors') or ["#2563eb", "#7c3aed", "#f8fafc"]

    # Parse colors if string
    if isinstance(colors, str):
        try:    
            colors = json.loads(colors)
        except: 
            colors = ["#2563eb", "#7c3aed", "#f8fafc"]
    if not colors or len(colors) < 3:
        colors = ["#2563eb", "#7c3aed", "#f8fafc"]

    # Parse services list
    svc_list = [s.strip() for s in str(services).split(',') if s.strip()]
    if not svc_list:
        svc_list = ["Professional Services", "Expert Consultation", "Quality Results"]

    hero_url, card_url, _, _ = get_images(btype)
    p, s = colors[0], colors[1]
    svc_lines = "\n".join(f"  - {sv}" for sv in svc_list)

    # Three distinct design styles
    DESIGNS = [
        {
            "name": "Dark Bold Hero",
            "font": "Montserrat",
            "nav":  f"position fixed, background rgba(0,0,0,0.96), white logo '{name}', white nav links",
            "hero": f"100vh height, background-image url('{hero_url}') cover with dark overlay rgba(0,0,0,0.6), centered white text, h1 font-size 4.5rem font-weight 900 Montserrat, subheading 1.2rem, CTA button background {p} color white border-radius 50px padding 18px 48px",
            "services_bg": "#ffffff",
            "card": f"white bg, box-shadow 0 4px 24px rgba(0,0,0,0.09), border-radius 12px, padding 32px, Font Awesome icon color {p} font-size 2rem, h3 font-weight 800, hover translateY(-6px)",
            "why":  f"background {p}, white text, 4 tiles with stats (500+ Clients, 10 Yrs Experience, 4.9 Star Rating, 24/7 Support)",
            "cta":  f"background linear-gradient(135deg, {p}, {s}), white text, white button",
            "footer": "background #0a0a0a, white text",
        },
        {
            "name": "Clean Corporate Split",
            "font": "Inter",
            "nav":  f"position fixed, background white, border-bottom 2px solid #f1f5f9, logo '{name}' color {p} font-weight 800",
            "hero": f"CSS grid 2 columns, NO top padding, full height: LEFT column background {p} padding 80px 60px white text h1 3.5rem font-weight 800 subtext CTA button white color {p} border-radius 8px; RIGHT column background-image url('{hero_url}') cover center min-height 100vh",
            "services_bg": "#f8fafc",
            "card": f"white bg, border 1px solid #e2e8f0, border-radius 10px, padding 28px, icon color {p}, h3 font-weight 700 color {p}, hover box-shadow increase",
            "why":  "background #1e293b (dark navy), white text, 4 stat tiles",
            "cta":  "background #111827, white text, gradient button",
            "footer": "background #1f2937, white text",
        },
        {
            "name": "Vibrant Gradient Creative",
            "font": "Poppins",
            "nav":  f"position fixed, background linear-gradient(135deg, {p}, {s}), white logo '{name}' font-weight 900, white links",
            "hero": f"background linear-gradient(135deg, {p} 0%, {s} 100%), min-height 92vh, flex center, h1 white font-size 5rem font-weight 900 letter-spacing -3px line-height 1.0, TWO buttons: (1) solid white color {p} border-radius 50px padding 18px 44px, (2) outline white transparent",
            "services_bg": "#ffffff",
            "card": f"white bg, border-top 4px solid {p}, border-radius 16px, padding 32px, icon inside circle background {p} color white, h3 font-weight 700, hover translateY(-6px) box-shadow increase",
            "why":  f"background linear-gradient(135deg, {p}20, {s}20) light tint, colored text, 4 stat tiles white bg",
            "cta":  f"background linear-gradient(135deg, {p}, {s}), white text, white button color {p}",
            "footer": "background #0f172a, white text",
        },
    ]

    d = DESIGNS[variation_index % 3]

    return (
        "Output ONLY a complete, valid HTML5 file. Start with <!DOCTYPE html>. End with </html>.\n"
        "Zero markdown. Zero backticks. Zero explanation.\n"
        "All CSS inside one <style> tag in <head>. All JS in <script> tags.\n"
        "Only Google Fonts and Font Awesome 6.5 from cdnjs CDN. No other external resources.\n"
        "No Bootstrap, No Tailwind. Fully responsive with @media(max-width:768px).\n\n"
        
        f"BUSINESS DETAILS:\n"
        f"  Name: {name}\n"
        f"  Industry: {btype}\n"
        f"  Location: {location}\n"
        f"  Primary Color: {p}\n"
        f"  Secondary Color: {s}\n"
        f"  Hero Image: {hero_url}\n"
        f"  About Image: {card_url}\n\n"
        
        f"SERVICES (create ONE card for EACH service with exact name):\n{svc_lines}\n\n"
        
        f"DESIGN STYLE: {d['name']}\n"
        f"  Font Family: {d['font']} from Google Fonts\n"
        f"  Navigation: {d['nav']}\n"
        f"  Hero: {d['hero']}\n"
        f"  Services BG: {d['services_bg']}\n"
        f"  Service Cards: {d['card']}\n"
        f"  Why Choose Us: {d['why']}\n"
        f"  CTA Section: {d['cta']}\n"
        f"  Footer: {d['footer']}\n\n"
        
        "BUILD THESE 9 SECTIONS:\n"
        f"1. STICKY NAVIGATION\n"
        f"   - Fixed header, logo '{name}'\n"
        f"   - Nav links: Services, About, Testimonials, Contact\n"
        f"   - 'Get Quote' CTA button (color {p})\n"
        f"   - Mobile hamburger menu (3 lines icon)\n\n"
        
        f"2. HERO SECTION (IMAGES CRITICAL - MUST DISPLAY)\n"
        f"   - HERO IMAGE: {hero_url}\n"
        f"   - Image MUST be visible: use background-image OR <img> tag\n"
        f"   - If background-image: add dark overlay for text contrast\n"
        f"   - If <img> tag: absolute position behind text with z-index\n"
        f"   - Image: width 100%, height 100%, object-fit cover\n"
        f"   - Image must load from URL - test in browser\n"
        f"   - Compelling headline (50-70 chars)\n"
        f"   - Benefit subheading (100+ chars)\n"
        f"   - Primary CTA button\n"
        f"   - Secondary CTA button (optional)\n\n"
        
        f"3. SERVICES SECTION (grid of {len(svc_list)}+ cards)\n"
        f"   - EACH SERVICE gets ONE card\n"
        f"   - Font Awesome icon appropriate to service\n"
        f"   - Service name as title (EXACT MATCH from input)\n"
        f"   - 2-3 sentence description with benefits\n"
        f"   - Hover effect (elevation or color change)\n\n"
        
        f"4. ABOUT US / WHY US SECTION (IMAGES CRITICAL - MUST DISPLAY)\n"
        f"   - Two column layout\n"
        f"   - LEFT: Image {card_url}\n"
        f"   - Image MUST be visible: <img src='{card_url}' alt='About' style='width:100%; height:auto; object-fit:cover;'>\n"
        f"   - Image: responsive, proper sizing\n"
        f"   - RIGHT: 3+ paragraphs (300+ words) about {name}\n"
        f"   - Mention business name and {location} naturally\n"
        f"   - Talk about: experience, values, commitment\n"
        f"   - Real, persuasive marketing copy\n\n"
        
        f"5. WHY CHOOSE US (stats section)\n"
        f"   - 4+ stat cards on colored background (color {p})\n"
        f"   - Realistic stats for {btype} industry\n"
        f"   - Examples: '500+ Clients', '10+ Years', '4.9 Rating', '24/7 Support'\n"
        f"   - Large numbers, concise labels\n\n"
        
        f"6. TESTIMONIALS (4-5 detailed review cards)\n"
        f"   - FULL 5-star display (★★★★★ in gold or color {p})\n"
        f"   - Genuine customer quote (2-3 sentences, NOT generic)\n"
        f"   - Customer name AND job title\n"
        f"   - Real sounding, specific praise\n"
        f"   - Card styling: white bg, subtle shadow\n\n"
        
        f"7. FAQ SECTION (5-6 accordion items)\n"
        f"   - Real questions people ask about {btype}\n"
        f"   - Detailed answers (2-3 sentences each)\n"
        f"   - Address common objections\n"
        f"   - Industry-specific language\n"
        f"   - Clickable accordion (expand/collapse)\n\n"
        
        f"8. CONTACT FORM (full-width section)\n"
        f"   - Full name input (required)\n"
        f"   - Email input (required, with validation)\n"
        f"   - Phone input (formatted)\n"
        f"   - Service dropdown (from your services list)\n"
        f"   - Message textarea (required)\n"
        f"   - Submit button (color {p})\n"
        f"   - Form styling: modern, accessible\n\n"
        
        f"9. FOOTER (multi-column)\n"
        f"   - Company info paragraph\n"
        f"   - Services list (links to each service)\n"
        f"   - Contact info (phone, email, location)\n"
        f"   - Social media links (icon placeholders)\n"
        f"   - Copyright 2025 {name}\n"
        f"   - Links to Privacy/Terms (optional)\n\n"
        
        "CRITICAL CONTENT REQUIREMENTS:\n"
        f"  ✓ Real, persuasive marketing copy (NO lorem ipsum)\n"
        f"  ✓ Mention '{name}' and '{location}' naturally throughout\n"
        f"  ✓ Hero headline: 50-70 characters, benefit-focused\n"
        f"  ✓ Hero subheading: 100+ characters, compelling\n"
        f"  ✓ Each service: 2-3 sentence description with outcomes\n"
        f"  ✓ About section: 300+ words, 3+ paragraphs, real story\n"
        f"  ✓ Testimonials: Sound genuine, specific praise, NOT generic\n"
        f"  ✓ FAQs: Real questions, detailed answers\n"
        f"  ✓ All text: Natural, authentic, professional tone\n\n"
        
        "CRITICAL IMAGE DISPLAY REQUIREMENTS (MUST FOLLOW):\n"
        f"  ✓ HERO IMAGE ({hero_url}):\n"
        f"    - Use as background-image with CSS background-size: cover\n"
        f"    - OR use <img> tag with position absolute, z-index -1\n"
        f"    - Always add semi-transparent overlay for text contrast\n"
        f"    - Set explicit width: 100% and height: 100vh or 90vh\n"
        f"    - Use background-position: center for backgrounds\n"
        f"    - TEST: Image must be visible when you render the HTML\n\n"
        f"  ✓ ABOUT SECTION IMAGE ({card_url}):\n"
        f"    - Use <img src='{card_url}' alt='About Our Business' />\n"
        f"    - Set width: 100%, height: auto, max-width: 500px\n"
        f"    - Add object-fit: cover for proper aspect ratio\n"
        f"    - Add border-radius: 12px for modern look\n"
        f"    - Set box-shadow: 0 10px 30px rgba(0,0,0,0.1)\n"
        f"    - TEST: Image must display clearly in two-column layout\n\n"
        f"  ✓ ALL IMAGES:\n"
        f"    - Use EXACT URLs provided - do NOT modify\n"
        f"    - Set crossOrigin='anonymous' if using <img> tags\n"
        f"    - Test loading in Chrome DevTools (Network tab)\n"
        f"    - Unsplash images: always public, always work\n"
        f"    - If image doesn't load, check console for CORS errors\n\n"
        
        "CRITICAL DESIGN & DISPLAY REQUIREMENTS:\n"
        f"  ✓ Images MUST LOAD: Use URLs exactly as provided\n"
        f"  ✓ Images MUST SHOW: VISIBLE in rendered website\n"
        f"  ✓ Hero image visible: proper contrast overlay\n"
        f"  ✓ All sections visible: NO display:none initially\n"
        f"  ✓ Hero height: 100vh or 90vh minimum\n"
        f"  ✓ Section padding: 60px 20px minimum (desktop)\n"
        f"  ✓ Typography: h1 3.5-5rem, h2 2-3rem, h3 1.3-1.8rem\n"
        f"  ✓ Mobile: ALL readable, sections stack, buttons full-width\n"
        f"  ✓ Spacing: Generous padding/margins (32px+ between sections)\n"
        f"  ✓ Grids: 3 columns desktop, 1-2 mobile for cards\n"
        f"  ✓ Colors: Use EXACT codes - {p} and {s}\n\n"
        
        "CRITICAL HTML/CSS REQUIREMENTS:\n"
        f"  ✓ Valid HTML5: proper semantic tags (nav, section, article, footer)\n"
        f"  ✓ Meta tags: charset UTF-8, viewport for mobile\n"
        f"  ✓ Images responsive: width 100%, height auto, max-width 100%\n"
        f"  ✓ Image alt text: descriptive for accessibility\n"
        f"  ✓ NO placeholder text: every word real and useful\n"
        f"  ✓ NO inline styles: use <style> section only\n"
        f"  ✓ Transitions smooth: all 0.3s cubic-bezier(0.4,0,0.2,1)\n"
        f"  ✓ Hover states: all interactive elements have :hover\n"
        f"  ✓ Mobile menu: hamburger nav for screens <768px\n"
        f"  ✓ Form inputs: styled, accessible, with labels\n"
        f"  ✓ SEO ready: proper heading hierarchy, semantic HTML\n"
        f"  ✓ Premium spacing: breathing room throughout\n"
    )

# ════════════════════════════════════════════════════════════════
#  GENERATE HTML via Gemini
# ════════════════════════════════════════════════════════════════

def generate_html(data, variation_index):
    """Generate HTML website using Gemini AI with robust error handling"""
    global LAST_AI_ERROR, ACTIVE_MODEL

    if not gemini_client:
        LAST_AI_ERROR = "GEMINI_API_KEY not set in environment variables"
        print(f"[DESIGN {variation_index}] ERROR: Gemini not initialized")
        return None

    prompt = build_prompt(data, variation_index)
    
    # Priority model list
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-flash-latest"
    ]

    for attempt in range(1, 3):  # 2 attempts
        for model_name in models_to_try:
            try:
                print(f"\n[DESIGN {variation_index}] Attempt {attempt}/2 with {model_name}")
                
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "temperature": 0.9,
                        "max_output_tokens": 18000,
                        "top_p": 0.95,
                    },
                )
                
                if not response:
                    print(f"[DESIGN {variation_index}] ERROR: Null response")
                    LAST_AI_ERROR = f"Null response from {model_name}"
                    continue
                
                if not response.text:
                    print(f"[DESIGN {variation_index}] ERROR: Empty response.text")
                    LAST_AI_ERROR = f"Empty response from {model_name}"
                    continue
                
                html = response.text.strip()
                
                # Validate
                if len(html) < 1000:
                    print(f"[DESIGN {variation_index}] ERROR: HTML too short ({len(html)} chars)")
                    LAST_AI_ERROR = f"Short HTML from {model_name}"
                    continue
                
                has_doctype = "<!DOCTYPE" in html.upper() or "<!doctype" in html.lower()
                has_html = "<html" in html.lower() and "</html>" in html.lower()
                has_body = "<body" in html.lower() and "</body>" in html.lower()
                has_images = ("unsplash.com" in html) or ("w=2560" in html) or ("w=1200" in html)
                
                print(f"[DESIGN {variation_index}] Validation: DOCTYPE={has_doctype}, HTML={has_html}, BODY={has_body}, IMAGES={has_images}, SIZE={len(html)}")
                
                if not (has_html and has_body):
                    print(f"[DESIGN {variation_index}] ERROR: Invalid structure")
                    LAST_AI_ERROR = f"Invalid HTML structure"
                    continue
                
                if not has_doctype:
                    html = "<!DOCTYPE html>\n" + html
                
                print(f"[DESIGN {variation_index}] ✓ SUCCESS!")
                LAST_AI_ERROR = ""
                return html
                    
            except Exception as e:
                error = str(e)[:150]
                print(f"[DESIGN {variation_index}] EXCEPTION {model_name}: {error}")
                LAST_AI_ERROR = error
                continue
        if attempt < 3:
            import time
            time.sleep(2)

    LAST_AI_ERROR = f"Failed to generate design {variation_index} after 3 attempts across all models"
    print(f"[DESIGN {variation_index}] FAILED: {LAST_AI_ERROR}")
    return None

# ════════════════════════════════════════════════════════════════
#  BANNER INJECTION & CONVERSION TRACKING
# ════════════════════════════════════════════════════════════════

def inject_banner(html, site_data, slug, base_url):
    """Inject banner with download/edit links"""
    banner_html = f'''
    <div style="
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 16px 24px;
        text-align: center;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        z-index: 9999;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    ">
        <div style="max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px;">
            <div style="font-size: 0.9rem;">
                <strong>✓ Website Generated!</strong> Download or edit your site.
            </div>
            <div style="display: flex; gap: 12px;">
                <a href="{base_url}/download/{slug}" style="
                    background: white;
                    color: #667eea;
                    padding: 10px 20px;
                    border-radius: 6px;
                    text-decoration: none;
                    font-weight: 600;
                    cursor: pointer;
                    border: none;
                    font-size: 0.9rem;
                ">📥 Download HTML</a>
                <a href="mailto:support@example.com?subject=Edit+{slug}" style="
                    background: rgba(255,255,255,0.2);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 6px;
                    text-decoration: none;
                    font-weight: 600;
                    cursor: pointer;
                    border: 1px solid white;
                    font-size: 0.9rem;
                ">✏️ Request Edit</a>
            </div>
        </div>
    </div>
    '''
    
    # Insert banner after body tag
    if '<body' in html:
        body_end = html.find('>') + 1
        return html[:body_end] + banner_html + html[body_end:]
    return html

# ════════════════════════════════════════════════════════════════
#  API ROUTES
# ════════════════════════════════════════════════════════════════

def html_r(body, status=200):
    """Return HTML response"""
    return Response(body.encode('utf-8'), status=status, mimetype='text/html; charset=utf-8')

@app.route('/')
def home():
    """Home page (form page)"""
    # In production, serve your HTML form from build-with-ai.html
    return jsonify({"message": "AI Web Architect Backend. Post to /api/generate-site"})

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "ok",
        "gemini": bool(gemini_client),
        "active_model": ACTIVE_MODEL,
        "last_error": LAST_AI_ERROR or "none",
        "database": bool(DATABASE_URL),
    })

@app.route('/api/debug')
def debug():
    """Debug endpoint"""
    return jsonify({
        "gemini_key_set": bool(GEMINI_KEY),
        "gemini_ready": bool(gemini_client),
        "active_model": ACTIVE_MODEL,
        "last_error": LAST_AI_ERROR or "none",
    })

@app.route('/api/generate-site', methods=['POST'])
def start_generation():
    """Register a new site generation job"""
    try:
        data = request.get_json()
        if not data or not data.get('businessName'):
            return jsonify({"success": False, "message": "businessName is required"}), 400
        
        # Create unique slug
        slug = re.sub(r'[^a-z0-9]+', '-', data['businessName'].lower().strip())
        slug = f"{slug}-{random.randint(10000, 99999)}"
        
        # Save to database
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
        cur.close()
        conn.close()
        
        return jsonify({"success": True, "slug": slug})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/generate-one/<slug>/<int:idx>')
def generate_one(slug, idx):
    """Generate one design variation"""
    try:
        if idx not in (0, 1, 2):
            return jsonify({"success": False, "message": "idx must be 0, 1 or 2"}), 400
        
        # Get site data
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()
        conn.close()
        
        if not site:
            return jsonify({"success": False, "message": "Site not found"}), 404
        
        # Generate HTML
        html = generate_html(dict(site), idx)
        if not html:
            return jsonify({"success": False, "message": LAST_AI_ERROR or "Generation failed"})
        
        # Save to database
        conn2 = get_db()
        cur2  = conn2.cursor()
        cur2.execute("DELETE FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        cur2.execute("INSERT INTO variations (site_slug,variation_index,html_content) VALUES (%s,%s,%s)",
                     (slug, idx, html))
        status = 'AWAITING_SELECTION' if idx == 2 else f'DONE_{idx}'
        cur2.execute("UPDATE sites SET status=%s WHERE slug=%s", (status, slug))
        conn2.commit()
        cur2.close()
        conn2.close()
        
        base = request.host_url.rstrip('/')
        return jsonify({
            "success": True,
            "variation_id": idx,
            "preview_url": f"{base}/view-design/{slug}/{idx}",
            "all_done": idx == 2,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/select-design', methods=['POST'])
def select_design():
    """Select and finalize a design"""
    data  = request.get_json() or {}
    slug  = data.get('slug')
    index = data.get('designIndex')
    
    if not slug or index is None:
        return jsonify({"success": False, "message": "slug and designIndex required"}), 400
    
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get variation
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s",
                    (slug, int(index)))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Design not found"}), 404
        
        # Get site info
        cur.execute("SELECT * FROM sites WHERE slug=%s", (slug,))
        site = cur.fetchone()
        
        # Inject banner and save final
        base = request.host_url.rstrip('/')
        final = inject_banner(row['html_content'], dict(site), slug, base)
        
        cur.execute("""INSERT INTO final_sites (site_slug,html_content)
            VALUES (%s,%s) ON CONFLICT (site_slug) DO UPDATE SET html_content=EXCLUDED.html_content""",
            (slug, final))
        cur.execute("UPDATE sites SET status='COMPLETED' WHERE slug=%s", (slug,))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"success": True, "previewUrl": f"{base}/s/{slug}", "downloadUrl": f"{base}/download/{slug}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/view-design/<slug>/<int:idx>')
def view_variation(slug, idx):
    """View a design variation"""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug=%s AND variation_index=%s", (slug, idx))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return html_r(row[0])
        return html_r("<h1>Design not found</h1>", 404)
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

@app.route('/s/<slug>')
def show_site(slug):
    """View final site"""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        
        if row:
            return html_r(row[0])
        return html_r("<h1>Site not found</h1>", 404)
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

@app.route('/download/<slug>')
def download(slug):
    """Download site as ZIP"""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug=%s", (slug,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return html_r("<h1>Site not found</h1>", 404)
        
        # Create ZIP file
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", row[0].encode('utf-8'))
        buf.seek(0)
        
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f"{slug}_website.zip")
    except Exception as e:
        return html_r(f"<h1>Error: {e}</h1>", 500)

# ════════════════════════════════════════════════════════════════
#  RUN SERVER
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)



