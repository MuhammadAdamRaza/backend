import os
import json
import sys
import shutil
import tempfile
import re
import subprocess
import requests
import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template_string, send_file
from flask_cors import CORS
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

import random
import psycopg2
from psycopg2.extras import RealDictCursor

# --- DATABASE CONFIG ---
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set. Please configure it in your environment variables.")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Sites table for metadata and status
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
    # Variations table for the 3 designs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS variations (
            id SERIAL PRIMARY KEY,
            site_slug TEXT REFERENCES sites(slug) ON DELETE CASCADE,
            variation_index INT,
            html_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Final sites table for the chosen design
    cur.execute("""
        CREATE TABLE IF NOT EXISTS final_sites (
            site_slug TEXT PRIMARY KEY REFERENCES sites(slug) ON DELETE CASCADE,
            html_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

if DATABASE_URL:
    with app.app_context():
        try:
            init_db()
            print("Neon Postgres Database initialized!")
        except Exception as e:
            print(f"Database init error: {e}")

# Progress store - now backed by DB for persistence
PROGRESS_STORE = {} 

# Initialize AI Clients
openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash") # Use stable flash model
if gemini_key:
    try:
        genai.configure(api_key=gemini_key, transport='rest')
        model = genai.GenerativeModel(gemini_model_name)
    except Exception as e:
        print(f"Gemini init error: {e}")
        model = None
else:
    model = None

# Global state for debugging
LAST_AI_ERROR = "No errors yet"

@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    import traceback
    traceback.print_exc()
    
    if isinstance(e, HTTPException):
        code = e.code
        message = e.description
    else:
        code = 500
        message = str(e)
        
    return jsonify({"success": False, "message": f"Server error: {message}", "code": code}), code

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PROJECT_ROOT should be the workspace root (one level up from backend/)
PROJECT_ROOT = os.path.dirname(BASE_DIR)

if os.getenv("VERCEL"):
    # On Vercel, /var/task is usually the root if deployed correctly
    WRITABLE_ROOT = "/tmp"
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com/MuhammadAdamRaza/backend/main"
else:
    WRITABLE_ROOT = PROJECT_ROOT
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com/MuhammadAdamRaza/backend/main/backend"

# Path helpers
SYSTEM_TEMPLATES_DIR = PROJECT_ROOT
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'src', 'assets')
PREVIEW_DIR = os.path.join(PROJECT_ROOT, 'preview')
TEMPLATES_DIR = PROJECT_ROOT
GENERATED_DIR = os.path.join(WRITABLE_ROOT, 'generated-sites')

# Ensure directories exist (only for local testing, skip on Vercel read-only FS)
if not os.getenv("VERCEL"):
    for d in [PROJECT_ROOT, ASSETS_DIR, PREVIEW_DIR]:
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except: pass

def ensure_file(rel_path):
    """Ensures a file exists locally. On Vercel, downloads to /tmp from GitHub if missing."""
    # 1. Check if it's in the read-only project bundle first
    bundle_path = os.path.join(PROJECT_ROOT, rel_path.replace('/', os.sep))
    if os.path.exists(bundle_path) and os.path.isfile(bundle_path):
        return bundle_path
        
    # 2. Check the writable /tmp/ (or same root if local)
    local_path = os.path.join(WRITABLE_ROOT, rel_path.replace('/', os.sep))
    if os.path.exists(local_path) and os.path.isfile(local_path):
        return local_path
    
    # 3. If missing, try to download to WRITABLE_ROOT
    if os.getenv("VERCEL") or GITHUB_RAW_BASE:
        try:
            url = f"{GITHUB_RAW_BASE}/{rel_path.replace(os.sep, '/')}"
            print(f"Fetching remote asset: {url}")
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(r.content)
                return local_path
        except Exception as e:
            print(f"Failed to fetch {rel_path}: {e}")
            
    return None

# Template functions removed - AI ONLY MODE

# Models initialized at top level

# Global config removed
# --- CONFIGURATION ---
AI_ONLY_MODE = True
UK_PRICE_SYMBOL = "£"
SYSTEM_TEMPLATES_DIR = PROJECT_ROOT

# Ensure system templates directory exists
if not os.path.exists(SYSTEM_TEMPLATES_DIR):
    os.makedirs(SYSTEM_TEMPLATES_DIR, exist_ok=True)

# --- REMOTE FETCH UTILS REMOVED - AI ONLY MODE ---
# Old template system completely removed

@app.route('/generated-sites/<path:filename>')
def serve_generated_sites(filename):
    """Serve any file from the generated sites directory."""
    try:
        # Use absolute path for reliability
        return send_from_directory(GENERATED_DIR, filename)
    except Exception as e:
        print(f"Error serving generated site: {filename} -> {e}")
        return jsonify({"success": False, "message": "File not found"}), 404
@app.route('/')
def home():
    try:
        template_path = ensure_file('index.html')
        if not template_path:
             return "<h1>Welcome</h1><p>System error: Core templates missing.</p>", 500
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        print(f"Error loading index.html: {e}")
        return "<h1>Welcome</h1><p>Error loading home page.</p>", 500

@app.route('/health')
def health():
    return jsonify({
        "status": "ok", 
        "environment": "vercel" if os.getenv("VERCEL") else "local",
        "base_dir": BASE_DIR,
        "project_root": PROJECT_ROOT,
        "preview_dir": PREVIEW_DIR,
        "templates_dir": TEMPLATES_DIR,
        "exists": {
            "preview": os.path.exists(PREVIEW_DIR),
            "templates": os.path.exists(TEMPLATES_DIR),
            "system_templates": os.path.exists(SYSTEM_TEMPLATES_DIR)
        },
        "ls": {
            "task": os.listdir("/var/task") if os.path.exists("/var/task") else [],
            "project_root": os.listdir(PROJECT_ROOT) if os.path.exists(PROJECT_ROOT) else [],
            "system_templates": os.listdir(SYSTEM_TEMPLATES_DIR) if os.path.exists(SYSTEM_TEMPLATES_DIR) else []
        }
    })

@app.route('/debug-fetch')
def debug_fetch():
    target = request.args.get('path', 'preview/awake/demo/src/html/index.html')
    local_path = ensure_file(target)
    exists = os.path.exists(local_path) if local_path else False
    
    # Try a simple HEAD request to GitHub to see if we can reach it
    status = "unknown"
    try:
        r = requests.head(f"{GITHUB_RAW_BASE}/{target}", timeout=5)
        status = f"HTTP {r.status_code}"
    except Exception as e:
        status = f"Connection failed: {str(e)}"
    
    return jsonify({
        "target": target,
        "local_path": local_path,
        "exists": exists,
        "github_status": status
    })

@app.route('/debug-env')
def debug_env():
    """Diagnostic endpoint to check environment variables."""
    return jsonify({
        "VERCEL": os.getenv("VERCEL"),
        "GEMINI_KEY_SET": bool(os.getenv("GEMINI_API_KEY")),
        "OPENAI_KEY_SET": bool(os.getenv("OPENAI_API_KEY")),
        "GEMINI_MODEL": os.getenv("GEMINI_MODEL"),
        "PYTHON_PATH": sys.path if 'sys' in globals() else "sys not imported",
        "DATABASE_URL_SET": bool(os.getenv("DATABASE_URL"))
    })

@app.route('/debug-ai-direct')
def debug_ai_direct():
    """Test AI generation directly and return the result/error."""
    try:
        global LAST_AI_ERROR
        status = {
            "gemini_available": bool(model),
            "openai_available": bool(client),
            "gemini_key_exists": bool(os.getenv("GEMINI_API_KEY")),
            "openai_key_exists": bool(os.getenv("OPENAI_API_KEY")),
            "gemini_model": gemini_model_name,
            "available_models": []
        }
        
        try:
            if gemini_key:
                models = genai.list_models()
                status["available_models"] = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        except Exception as e:
            status["model_list_error"] = str(e)
        if not model and not client:
            return jsonify({
                "success": False, 
                "message": "No AI model available. Check your API keys.", 
                "status": status,
                "last_error": LAST_AI_ERROR
            }), 500
            
        test_data = {
            "businessName": "Debug Test",
            "businessType": "agency",
            "location": "London",
            "services": "Testing",
            "style": "modern",
            "colors": ["#000000", "#ffffff", "#cccccc"]
        }
        
        result = generate_custom_site_html(test_data)
        if result:
            return jsonify({
                "success": True, 
                "message": "AI generation test successful!", 
                "length": len(result),
                "status": status
            })
        else:
            return jsonify({
                "success": False, 
                "message": "generate_custom_site_html returned None",
                "last_error": LAST_AI_ERROR,
                "status": status
            }), 500
    except Exception as e:
        import traceback
        LAST_AI_ERROR = str(e) + "\n" + traceback.format_exc()
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@app.route('/build-with-ai')
def build_with_ai_page():
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'build-with-ai.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        return "<h1>Error</h1>", 500

@app.route('/dashboard')
def dashboard():
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'dashboard.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        return "<h1>Error</h1>", 500

@app.route('/contact')
def contact_page():
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'contact.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        return "<h1>Error</h1>", 500

@app.route('/about')
def about_page():
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'about.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        return "<h1>Error</h1>", 500

@app.route('/services')
def services_page():
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'services.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content)
    except Exception as e:
        return "<h1>Error</h1>", 500

@app.route('/hosting/setup/<slug>')
def hosting_setup(slug):
    try:
        template_path = os.path.join(SYSTEM_TEMPLATES_DIR, 'hosting-setup.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        return render_template_string(template_content, slug=slug)
    except Exception as e:
        return f"<h1>Error</h1>", 500


@app.route('/api/plans')
def get_plans():
    return jsonify([
        {"id": "basic", "name": "Basic", "price": "£9/mo", "features": ["1 Website", "Standard Speed", "Basic SEO"]},
        {"id": "pro", "name": "Pro", "price": UK_PRICE_SYMBOL + "19/mo", "features": ["5 Websites", "Ultra Fast", "Advanced SEO"]},
        {"id": "business", "name": "Business", "price": UK_PRICE_SYMBOL + "49/mo", "features": ["Unlimited Sites", "Priority Support", "Email Included"]}
    ])


@app.route('/api/hosting/activate/<slug>', methods=['POST'])
def activate_hosting(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Check if site exists
        cur.execute("SELECT slug FROM sites WHERE slug = %s", (slug,))
        if not cur.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Site not found"}), 404
            
        # Update status to 'LIVE'
        cur.execute("UPDATE sites SET status = %s WHERE slug = %s", ('LIVE', slug))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# hosting_setup route is defined above at /hosting/setup/<slug> using render_template_string

def deploy_to_vercel(folder_path, project_name):
    """Deploy the generated site folder to Vercel using npx vercel CLI."""
    token = os.getenv("VERCEL_TOKEN")
    if os.getenv("VERCEL"):
        print("Vercel deployment skipped on Vercel runtime.")
        return None

    try:
        # Run vercel deploy using npx
        # --token: Authentication
        # --name: Specific project name
        # --yes: Skip confirmation
        # --prod: Deploy to production (not just preview)
        # Use npx -y to avoid interactive installation prompts
        cmd = ["npx", "-y", "vercel", "deploy", folder_path, "--token", token, "--name", project_name, "--yes", "--prod"]
        # Print without token for security
        print(f"Running Vercel deployment: {' '.join([str(c) for c in cmd if c != token])} [TOKEN HIDDEN]")
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # The deployment URL is usually the last line of the output
        output = result.stdout.strip()
        print(f"Vercel raw output: {output}")
        
        # Regex to find https://*.vercel.app
        urls = re.findall(r'https://[a-zA-Z0-9.-]+\.vercel\.app', output)
        if urls:
            deployment_url = urls[-1] # Take the last one (usually the production URL)
            print(f"Vercel Deployment Successful: {deployment_url}")
            return deployment_url
        
        lines = output.splitlines()
        if lines:
            deployment_url = lines[-1].strip()
            if deployment_url.startswith("https://"):
                return deployment_url
        
        print(f"Vercel Deployment output (unsure of URL): {output}")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Vercel Deployment Error: {e.stderr}")
        return None
    except Exception as e:
        print(f"Unexpected error during Vercel deployment: {e}")
        return None


@app.route('/api/sites')
def list_sites():
    """List all AI-generated sites from DB."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT slug, business_name as name, status FROM sites ORDER BY created_at DESC")
        sites = cur.fetchall()
        conn.close()
        return jsonify(sites)
    except Exception as e:
        return jsonify([])

@app.route('/src/<path:path>')
def serve_src(path):
    """Serve source assets like CSS, JS, and images."""
    rel_path = f"src/{path}"
    ensure_file(rel_path)
    return send_from_directory(os.path.join(PROJECT_ROOT, 'src'), path)

def generate_custom_site_html(data, variation_index=0):
    """Generate a completely unique, beautiful single-page website using AI.
    
    This function uses multiple design patterns, randomized layouts, and
    industry-specific aesthetics to ensure each generated site is unique.
    """
    if not model and not client:
        print("No AI model available")
        return None
    
    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'business')
    location = data.get('location', 'International')
    style = data.get('style', 'modern')
    services = data.get('services', 'Expert services')
    user_colors = data.get('colors', []) # Expecting [primary, secondary, accent]
    
    # Parse services into a list
    services_list = [s.strip() for s in services.split(',') if s.strip()]
    if not services_list:
        services_list = ['Professional Services', 'Expert Solutions', 'Quality Service']
    
    # Random design patterns for uniqueness - each generation picks different patterns
    import random
    
    layout_patterns = [
        "Hero with split-screen image + text, staggered services grid below",
        "Full-screen hero with overlay, floating cards for services in wave pattern",
        "Minimalist hero with giant typography, bento grid layout for services",
        "Diagonal section dividers, hero with parallax background, masonry service grid",
        "Asymmetric hero with image on right, services as horizontal scroll cards",
        "Centered hero with animated gradient background, services as icon + text tiles",
        "Layered glassmorphism panels, oversized typography, circular service icons",
        "Vertical sidebar menu for desktop, split hero with immersive video/image background",
        "Magazine-style editorial layout, large whitespace, overlapping image/text blocks"
    ]
    
    nav_patterns = [
        "Fixed transparent navbar that turns solid on scroll",
        "Floating pill-shaped navbar centered at top",
        "Sidebar navigation that slides in from left on mobile",
        "Minimal navbar with just logo and hamburger menu",
        "Navbar that hides on scroll down, shows on scroll up"
    ]
    
    animation_patterns = [
        "Smooth fade-in-up animations on scroll, hover lift effects",
        "Subtle parallax on background, scale effects on images",
        "Staggered reveal animations, magnetic button effects",
        "Typewriter text effect on headline, morphing shapes",
        "Scroll-triggered slide-ins, elastic hover transitions"
    ]
    
    # Select patterns based on variation index and random offset to ensure total uniqueness
    pattern_offset = random.randint(0, 100)
    selected_layout = layout_patterns[(variation_index + pattern_offset) % len(layout_patterns)]
    selected_nav = nav_patterns[(variation_index + pattern_offset) % len(nav_patterns)]
    selected_anim = animation_patterns[(variation_index + pattern_offset) % len(animation_patterns)]
    
    # Style-specific design tokens with multiple options per style
    style_design_systems = {
        "modern": {
            "desc": "Sleek, futuristic, high-contrast with vibrant gradients",
            "colors": [
                "#0a0a0a background with #6366f1, #8b5cf6, #d946ef gradient accents",
                "#ffffff background with #0ea5e9, #6366f1, #a855f7 gradient accents",
                "#1e1b4b background with #22d3ee, #818cf8, #c084fc gradient accents"
            ],
            "typography": ["Inter, system-ui, sans-serif", "Plus Jakarta Sans, sans-serif", "Space Grotesk, sans-serif"],
            "effects": ["glassmorphism cards with backdrop-filter blur", "gradient borders, glowing hover states", "subtle grid background pattern"]
        },
        "professional": {
            "desc": "Corporate, trustworthy with refined, editorial aesthetic",
            "colors": [
                "#fafaf9 background with #1e3a5f, #c9a227, #2d5a87 accents",
                "#ffffff background with #0f172a, #475569, #94a3b8 accents",
                "#f8fafc background with #1e293b, #334155, #0f172a accents"
            ],
            "typography": ["DM Serif Display for headings + Inter for body", "Playfair Display + Source Sans Pro", "Libre Baskerville + Open Sans"],
            "effects": ["subtle shadows, clean borders", "elegant dividers, refined spacing", "professional card layouts"]
        },
        "creative": {
            "desc": "Bold, vibrant, artistic with experimental layouts",
            "colors": [
                "#fef3c7 background with #f59e0b, #ec4899, #8b5cf6, #06b6d4 bold accents",
                "#1a1a2e background with #e94560, #0f3460, #533483, #16213e vibrant contrast",
                "#f0fdf4 background with #16a34a, #dc2626, #2563eb playful color pops"
            ],
            "typography": ["Bebas Neue for headlines + Poppins for body", "Clash Display + Satoshi", "Tanker + General Sans"],
            "effects": ["geometric shapes, organic blobs", "textured backgrounds, grain overlays", "asymmetric grids, overlapping elements"]
        },
        "minimal": {
            "desc": "Elegant, airy with Apple-esque simplicity and focus on typography",
            "colors": [
                "#ffffff background with #18181b text and #71717a subtle accents",
                "#fafafa background with #171717 text and #e5e5e5 borders",
                "#f5f5f5 background with #262626 text and #a3a3a3 secondary text"
            ],
            "typography": ["SF Pro Display system font, generous line-height", "Neue Montreal + DM Sans", "Graphik + Untitled Sans"],
            "effects": ["extreme whitespace, subtle micro-interactions", "single accent color used sparingly", "refined hover states"]
        }
    }
    
    # Select variations within the style
    style_config = style_design_systems.get(style, style_design_systems["modern"])
    
    if user_colors and len(user_colors) >= 3:
        selected_colors = f"Primary: {user_colors[0]}, Secondary: {user_colors[1]}, Accent: {user_colors[2]}"
    else:
        selected_colors = random.choice(style_config["colors"])
        
    selected_typography = random.choice(style_config["typography"])
    selected_effects = random.choice(style_config["effects"])
    
    # Generate unique color variations for this specific site
    unique_id = random.randint(1000, 9999)
    
    # Build services section content
    services_html = "\n".join([f'<div class="service-item"><h3>{s}</h3><p>Expert {s} tailored for your needs in {location}.</p></div>' for s in services_list[:4]])
    
    # Enhanced prompt with explicit uniqueness requirements
    prompt = f"""You are the Lead Creative Director at a world-renowned luxury digital agency that charges £50,000+ per website.

MISSION: Create a COMPLETELY UNIQUE, BESPOKE single-file HTML5 landing page for '{business_name}' — a {business_type} business based in {location}.

---
DESIGN SPECIFICATIONS (SITE #{unique_id}):
---

LAYOUT PATTERN: {selected_layout}
NAVIGATION: {selected_nav}
ANIMATIONS: {selected_anim}

COLOR PALETTE: {selected_colors} (CRITICAL: Use these EXACT colors in CSS variables)
TYPOGRAPHY: {selected_typography}
VISUAL EFFECTS: {selected_effects}
VARIATION ID: Design Option #{variation_index + 1}

SERVICES TO FEATURE: {', '.join(services_list)}

---
REQUIRED SECTIONS:
---
1. HERO: Full-viewport or oversized hero with:
   - Unique, benefit-driven headline (NOT generic "Welcome to")
   - Compelling subheadline about their specific services in {location}
   - Strong CTA button
    - BACKGROUND IMAGE: Use a high-quality, high-resolution (HD) professional image related to {business_type} in {location}. 
      URL PATTERN (MANDATORY: Use ONLY this format for HD images): https://loremflickr.com/1920/1080/{business_type.replace(' ', ',')},professional,hd,high-res
      (Alternative for variety: https://source.unsplash.com/featured/1920x1080?{business_type.replace(' ', ',')},highres)
    - CTAs: Visible and contrasting

2. SERVICES SECTION: Use this layout pattern: {selected_layout}
   - Showcase these services: {', '.join(services_list)}
   - Each service needs: icon (FontAwesome), title, 2-sentence description
    - IMAGE: Include a relevant professional service image for each card:
      URL PATTERN (HD QUALITY): https://loremflickr.com/800/600/{business_type},{{service_keyword}},professional,detailed
   - Make it visually distinct from typical template layouts

3. ABOUT/VALUE SECTION: 
   - Why choose {business_name} in {location}
   - Trust indicators, local expertise angle

4. CONTACT/CTA SECTION:
   - Clear contact form or CTA
   - Location mention: {location}
   - Business email: info@{business_name.lower().replace(' ', '').replace("'", '')}.com

5. FOOTER: Minimal with business name, copyright, contact

---
TECHNICAL REQUIREMENTS:
---
- COMPLETE single HTML file with embedded CSS in <style> and JS in <script>
- NO external CSS/JS except: Google Fonts and FontAwesome (CDN)
- NO Bootstrap, NO Tailwind — use pure CSS with custom properties (CSS variables)
- CSS Grid and Flexbox for layouts — avoid floats
- Responsive: desktop → tablet → mobile breakpoints
- Performance-optimized CSS

MUST-HAVE CSS FEATURES:
- CSS custom properties for colors
- Backdrop-filter blur effects where appropriate
- CSS Grid with template-areas
- Smooth transitions (0.3s ease or cubic-bezier)
- Intersection Observer for scroll animations
- Mobile-first media queries

---
CRITICAL RULES:
---
- The design MUST look NOTHING like a template — unique layout, unique proportions
- VARIATION DESIGN: This is Design Variation #{variation_index + 1} of 3. Ensure it is visually distinct from others.
- Use the selected Layout pattern: {selected_layout}
- Use unexpected spacing, asymmetric layouts, creative visual hierarchies
- Each element should feel considered and custom-designed
- No lorem ipsum — write real, compelling copy specific to {business_type} in {location}
- CRITICAL: Use REAL industry-specific images. ONLY use HD professional source URLs like https://loremflickr.com/1920/1080/{business_type.replace(' ', ',')},professional,hd
- NO markdown code blocks in output
- Return ONLY the raw HTML code starting with <!DOCTYPE html>
- Minimum 2000 characters of code (this is a full website, not a snippet)
"""
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            temperature = 0.9 if attempt == 0 else 0.95  # Increase creativity on retry
            
            if model:
                generation_config = genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=8192,
                    top_p=0.95,
                    top_k=40
                )
                try:
                    # Try a few different model names in case of availability issues
                    primary_model_name = os.getenv("GEMINI_MODEL")
                    model_names = []
                    if primary_model_name:
                        model_names.append(primary_model_name)
                    
                    # Known working models
                    model_names.extend(["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-pro"])
                    
                    # Remove duplicates while preserving order
                    model_names = list(dict.fromkeys(model_names))
                    
                    response = None
                    last_err = ""
                    
                    for m_name in model_names:
                        try:
                            print(f"Attempting generation with model: {m_name}")
                            temp_model = genai.GenerativeModel(m_name)
                            response = temp_model.generate_content(prompt, generation_config=generation_config)
                            if response and response.text:
                                print(f"Success with model: {m_name}")
                                break
                        except Exception as e:
                            last_err = str(e)
                            print(f"Model {m_name} failed: {e}")
                            continue
                    
                    if not response or not response.text:
                        raise Exception(f"All AI models failed. Last error: {last_err}")
                        
                    html_code = response.text.strip()
                except Exception as e:
                    # Re-raise to be caught by the outer attempt loop
                    raise e
            elif client:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a master web designer who creates unique, luxury websites. You write production-ready, complete HTML5 code with embedded CSS and JavaScript. Never use templates or generic layouts."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=8000,
                    temperature=temperature
                )
                html_code = response.choices[0].message.content.strip()
            else:
                return None

            # Extract HTML if wrapped
            if "<!DOCTYPE" in html_code.upper():
                idx = html_code.upper().find("<!DOCTYPE")
                html_code = html_code[idx:]
            elif "```html" in html_code:
                html_code = html_code.split("```html")[1].split("```")[0].strip()
            elif "```" in html_code:
                parts = html_code.split("```")
                for part in parts:
                    if "<html" in part.lower() or "<!doctype" in part.lower():
                        html_code = part.strip()
                        break
            
            # Validate quality
            if len(html_code) < 1500:
                print(f"Attempt {attempt + 1}: Generated HTML too short ({len(html_code)} chars), retrying...")
                if attempt == max_retries - 1:
                    print("AI generation failed after all retries")
                    return None
                continue
            
            # Validate required elements
            required_elements = ['<html', '<head', '<style', '<body', '</html>']
            missing = [el for el in required_elements if el not in html_code.lower()]
            if missing:
                print(f"Attempt {attempt + 1}: Missing elements: {missing}, retrying...")
                if attempt == max_retries - 1:
                    print("AI generation failed - incomplete HTML")
                    return None
                continue
                
            print(f"Successfully generated unique site ({len(html_code)} chars)")
            
            # Post-process to ensure NO broken Unsplash Source links and enforce HD keywords
            unsplash_pattern = r'(?:https?://)?source\.unsplash\.com/featured/(?P<dim>\d+x\d+)\?(?P<query>[^"\']+)'
            def replace_unsplash(match):
                dim = match.group('dim').replace('x', '/')
                query = match.group('query').replace(' ', ',').replace('+', ',')
                # Enforce high-end professional keywords
                return f"https://loremflickr.com/{dim}/{query},professional,hd,luxury,high-resolution"
            
            html_code = re.sub(unsplash_pattern, replace_unsplash, html_code)
            
            # Catch raw unsplash domain usages without queries
            html_code = html_code.replace("source.unsplash.com", "loremflickr.com/1920/1080/professional,hd,luxury")
            
            # Ensure protocol for any remaining loremflickr links
            html_code = re.sub(r'(?<!https://)(?<!http://)loremflickr\.com', 'https://loremflickr.com', html_code)
            
            # Clean up potential duplicate protocols
            html_code = html_code.replace("https://https://", "https://")
            html_code = html_code.replace("http://https://", "https://")
            
            return html_code
            
        except Exception as e:
            global LAST_AI_ERROR
            LAST_AI_ERROR = f"Attempt {attempt + 1} error: {str(e)}"
            print(f"Attempt {attempt + 1} error: {e}")
            if attempt == max_retries - 1:
                print("AI generation failed with exception")
                return None
    
    return None


def generate_unique_site(data):
    """Generate a unique, modern website programmatically when AI is unavailable.
    
    This creates a custom site with user colors if provided.
    """
    import random
    
    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'business')
    location = data.get('location', 'Your Area')
    services = data.get('services', 'Expert Services')
    style = data.get('style', 'modern')
    user_colors = data.get('colors', [])
    
    services_list = [s.strip() for s in services.split(',') if s.strip()][:4]
    if len(services_list) < 2:
        services_list = ['Professional Service', 'Expert Solutions', 'Quality Care']
    
    # Random design variations for uniqueness
    hues = [220, 260, 280, 320, 340, 200, 240, 300]  # Different color hues
    hue1 = random.choice(hues)
    hue2 = (hue1 + random.randint(30, 60)) % 360
    
    # Industry-specific content mappings
    category_data = {
        'plumber': {'keywords': 'plumbing,repair', 'desc': 'Professional reliable plumbing services.'},
        'electrician': {'keywords': 'electrician,power', 'desc': 'Certified electrical solutions.'},
        'restaurant': {'keywords': 'luxury,dining', 'desc': 'Exquisite dining experiences.'},
        'law': {'keywords': 'law,office', 'desc': 'Expert legal advocacy.'},
        'consulting': {'keywords': 'business,corporate', 'desc': 'Strategic growth consulting.'},
        'fitness': {'keywords': 'gym,workout', 'desc': 'Personalized wellness programs.'},
        'realestate': {'keywords': 'luxury,modern,house', 'desc': 'Premium property listings.'},
        'portfolio': {'keywords': 'professional,design', 'desc': 'Showcasing high-impact work.'},
        'agency': {'keywords': 'corporate,office', 'desc': 'Full-service digital agency.'},
        'other': {'keywords': 'business,office', 'desc': 'High-quality professional services.'}
    }
    
    cat_info = category_data.get(business_type, category_data['other'])
    main_kw = cat_info['keywords']
    
    # Unique CSS based on selected style or user colors
    if user_colors and len(user_colors) >= 3:
        bg_color = user_colors[0]
        text_color = "#ffffff" if style != "minimal" else "#1a1a1a"
        accent_gradient = f"linear-gradient(135deg, {user_colors[1]} 0%, {user_colors[2]} 100%)"
    else:
        bg_color = '#0a0a0a' if style == 'modern' else '#fafafa'
        text_color = '#fafafa' if style == 'modern' else '#1a1a1a'
        accent_gradient = 'linear-gradient(135deg, #6e8efb 0%, #a777e3 100%)'

    try:
        template_path = ensure_file('fallback_site.html')
        if not template_path:
             raise FileNotFoundError("fallback_site.html not found")
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
            
        return render_template_string(
            template_content,
            business_name=business_name,
            business_type=business_type,
            location=location,
            bg_color=bg_color,
            text_color=text_color,
            accent_gradient=accent_gradient,
            main_kw=main_kw,
            services_list=services_list,
            cat_info_desc=cat_info.get('desc', 'Professional services'),
            feature_icon_color=f"hsl({hue1}, 80%, 60%)",
            email_domain=business_name.lower().replace(' ', '').replace("'", ""),
            current_year=datetime.datetime.now().year
        )
    except Exception as e:
        print(f"Error loading unique site template: {e}")
        return f"Error: Failed to generate site for {business_name}"


# Remove the old fallback template system entirely
def generate_fallback_site(data):
    """Guaranteed high-quality site generation when AI fails.
    
    This is the ultimate safety net. It uses generate_unique_site to create
    a bespoke experience without relying on external AI models.
    """
    try:
        print("Executing guaranteed fallback generator...")
        return generate_unique_site(data)
    except Exception as e:
        print(f"Fallback generator failed: {e}")
        return f"Error: Fallback engine failure"

@app.route('/api/generate-site', methods=['POST', 'OPTIONS'])
def generate_site():
    if request.method == "OPTIONS":
        return jsonify({"success": True}), 204
    if not model and not client:
        return jsonify({
            "success": False, 
            "message": "No AI model available. Please configure GEMINI_API_KEY in Vercel Environment Variables."
        }), 500
        
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "message": "Missing request data"}), 400
            
        business_name = data.get('businessName', 'My Business')
        site_slug = business_name.lower().replace(" ", "-").replace("'", "").replace("\"", "")
        site_slug = f"{site_slug}-{random.randint(1000, 9999)}"
        
        # 1. Initialize Site in DB with STARTING status
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sites (slug, business_name, business_type, location, services, style, colors, status, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (site_slug, business_name, data.get('businessType'), data.get('location'), 
                  data.get('services'), data.get('style'), data.get('colors'), 'STARTING', 'Architect is preparing the design environment...'))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"DB Insert Error: {e}")
            return jsonify({"success": False, "message": "Database error"}), 500

        return jsonify({
            "success": True, 
            "slug": site_slug, 
            "status": "STARTING",
            "message": "Generation started. Please poll status to continue."
        })
            
    except Exception as e:
        import traceback
        print(f"API Error: {traceback.format_exc()}")
        return jsonify({"success": False, "message": f"Initialization failed: {str(e)}"}), 500

@app.route('/api/select-design', methods=['POST'])
def select_design():
    data = request.json
    slug = data.get('slug')
    design_index = data.get('designIndex')
    
    if not slug or design_index is None:
        return jsonify({"success": False, "message": "Missing slug or design choice"}), 400
        
    try:
        # 1. Fetch the chosen variation from DB
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug = %s AND variation_index = %s", (slug, int(design_index)))
        row = cur.fetchone()
        
        if not row:
            conn.close()
            return jsonify({"success": False, "message": "Selected design not found in database"}), 404
            
        chosen_html = row[0]
        
        # 2. Create the Preview Wrapper
        business_name = slug.split('-')[0].title()
        base_url = request.host_url.rstrip('/')
        # Internal URL for the variation to be used in iframe
        view_source_url = f"{base_url}/view-design/{slug}/{design_index}"
        
        try:
            template_path = ensure_file('preview_wrapper.html')
            if not template_path:
                 raise FileNotFoundError("preview_wrapper.html not found")
                 
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            preview_bar_html = render_template_string(
                template_content,
                business_name=business_name,
                view_source_url=view_source_url
            )
        except Exception as e:
            print(f"Error loading preview wrapper template: {e}")
            preview_bar_html = f"Error: Preview system failure"
        
        # 3. Store the finalized site (wrapper + content) in DB
        cur.execute("""
            INSERT INTO final_sites (site_slug, html_content)
            VALUES (%s, %s)
            ON CONFLICT (site_slug) DO UPDATE SET html_content = EXCLUDED.html_content
        """, (slug, preview_bar_html))
        
        # Update site status
        cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s", ('COMPLETED', 'Website finalized!', slug))
        
        conn.commit()
        conn.close()
        
        preview_url = f"{base_url}/s/{slug}"
        if slug in PROGRESS_STORE:
            PROGRESS_STORE[slug].update({"status": "COMPLETED", "previewUrl": preview_url})
            
        return jsonify({"success": True, "previewUrl": preview_url})
    except Exception as e:
        import traceback
        print(f"Selection error: {traceback.format_exc()}")
        return jsonify({"success": False, "message": f"Selection failed: {str(e)}"}), 500

@app.route('/api/status/<path:slug>')
def get_site_status(slug):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM sites WHERE slug = %s", (slug,))
        site = cur.fetchone()
        
        if not site:
            conn.close()
            return jsonify({"status": "NOT_FOUND", "message": "Site not found"}), 404
            
        current_status = site['status']
        
        # INCREMENTAL GENERATION LOGIC
        # If status is STARTING, generate var 0
        # If status is AI_CODE_GEN_0, generate var 1
        # If status is AI_CODE_GEN_1, generate var 2
        # After var 2, status becomes WAITING_FOR_SELECTION
        
        target_variation = -1
        next_status = ""
        
        if current_status == 'STARTING':
            target_variation = 0
            next_status = 'AI_CODE_GEN_0'
        elif current_status == 'AI_CODE_GEN_0':
            target_variation = 1
            next_status = 'AI_CODE_GEN_1'
        elif current_status == 'AI_CODE_GEN_1':
            target_variation = 2
            next_status = 'WAITING_FOR_SELECTION'
            
        if target_variation != -1:
            print(f"Incremental generation: variation {target_variation} for {slug}")
            # Prep data for generation
            gen_data = {
                "businessName": site['business_name'],
                "businessType": site['business_type'],
                "location": site['location'],
                "services": site['services'],
                "style": site['style'],
                "colors": site['colors']
            }
            
            custom_html = None
            try:
                custom_html = generate_custom_site_html(gen_data, variation_index=target_variation)
            except Exception as e:
                print(f"AI Generation variation {target_variation} failed: {e}")

            if not custom_html:
                custom_html = generate_fallback_site(gen_data)
            
            if custom_html:
                # Save variation to DB
                cur.execute("""
                    INSERT INTO variations (site_slug, variation_index, html_content)
                    VALUES (%s, %s, %s)
                """, (slug, target_variation, custom_html))
                
                # Update main site status
                msg = f"Variation {target_variation + 1} ready!" if target_variation < 2 else "All designs are ready! Please choose one."
                cur.execute("UPDATE sites SET status = %s, message = %s WHERE slug = %s", (next_status, msg, slug))
                conn.commit()
                
                # Update local site object for response
                site['status'] = next_status
                site['message'] = msg

        # Prepare response
        response_data = {
            "status": site['status'],
            "message": site['message'],
            "slug": slug
        }
        
        if site['status'] == 'COMPLETED':
            base_url = request.host_url.rstrip('/')
            response_data['previewUrl'] = f"{base_url}/s/{slug}"
            
        # Get variations if they are ready
        if site['status'] in ['WAITING_FOR_SELECTION', 'COMPLETED', 'AI_CODE_GEN_0', 'AI_CODE_GEN_1']:
            cur.execute("SELECT variation_index FROM variations WHERE site_slug = %s", (slug,))
            vars = cur.fetchall()
            base_url = request.host_url.rstrip('/')
            response_data['variations'] = [{"id": v['variation_index'], "url": f"{base_url}/view-design/{slug}/{v['variation_index']}"} for v in vars]

        conn.close()
        return jsonify(response_data)
    except Exception as e:
        import traceback
        print(f"Status check error: {traceback.format_exc()}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/s/<path:slug>')
def view_final_site(slug):
    """Serve the finalized high-quality site from DB."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return "Site not found or not finalized", 404
            
        return row[0]
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/view-design/<slug>/<int:design_index>')
def view_design_variation(slug, design_index):
    """Serve a specific design variation for preview in iframe."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM variations WHERE site_slug = %s AND variation_index = %s", (slug, design_index))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return "Design variation not found", 404
            
        return row[0]
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/download/<slug>')
def download_site(slug):
    import io
    import zipfile
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT html_content FROM final_sites WHERE site_slug = %s", (slug,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return "Site not found or not finalized", 404
            
        html_content = row[0]
        
        # Create ZIP in-memory using BytesIO
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("index.html", html_content)
        
        memory_file.seek(0)
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{slug}_website.zip"
        )
    except Exception as e:
        return f"Download error: {str(e)}", 500

if __name__ == '__main__':
    print("Starting AI Website Builder backend on http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)