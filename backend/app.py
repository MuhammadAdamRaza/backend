import os
import json
import shutil
import tempfile
import re
import subprocess
import requests
import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
CORS(app)

# Progress store for site generation
PROGRESS_STORE = {}
import threading

# Initialize AI Clients
openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key) if openai_key else None

gemini_key = os.getenv("GEMINI_API_KEY")
gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(gemini_model_name)
else:
    model = None

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    traceback.print_exc()
    return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getenv("VERCEL"):
    # On Vercel, we work in /tmp for write access and to avoid bundle size issues
    PROJECT_ROOT = "/tmp"
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com/MuhammadAdamRaza/awake/main"
else:
    PROJECT_ROOT = os.path.dirname(BASE_DIR)
    GITHUB_RAW_BASE = None

TEMPLATES_DIR = os.path.join(PROJECT_ROOT, 'templates')
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'src', 'assets')
PREVIEW_DIR = os.path.join(PROJECT_ROOT, 'preview')
GENERATED_DIR = os.path.join(PROJECT_ROOT, 'generated-sites')

# Ensure directories exist
for d in [PROJECT_ROOT, GENERATED_DIR, TEMPLATES_DIR, PREVIEW_DIR, ASSETS_DIR]:
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def ensure_file(rel_path):
    """Ensures a file exists locally. Only used for non-template assets now."""
    # Check local bundle
    bundle_path = os.path.join(os.path.dirname(BASE_DIR), rel_path.replace('/', os.sep))
    if os.path.exists(bundle_path):
        return bundle_path
        
    # Check project root
    local_path = os.path.join(PROJECT_ROOT, rel_path.replace('/', os.sep))
    if os.path.exists(local_path):
        return local_path
    
    return None

# Template functions removed - AI ONLY MODE

# Models initialized at top level

# Global config removed - AI only
AI_ONLY_MODE = True

# --- EMBEDDED UI STRINGS ---
# These are the full HTML contents previously in separate files.
# I am using CDN links for all CSS/JS to ensure they work without the 'src' folder.

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Free Website Templates</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.css">
  <style>
    :root { --primary: #6e8efb; --secondary: #a777e3; --dark: #1a1a1a; }
    body { font-family: 'Inter', sans-serif; background: #f8f9fa; color: var(--dark); }
    .hero { padding: 100px 0; background: linear-gradient(135deg, #fdfbfb 0%, #ebedee 100%); }
    .btn-ai { background: linear-gradient(135deg, var(--primary), var(--secondary)); border: none; color: #fff; padding: 15px 40px; border-radius: 50px; font-weight: 700; transition: transform 0.3s; }
    .btn-ai:hover { transform: translateY(-3px); box-shadow: 0 10px 20px rgba(110, 142, 251, 0.3); color: #fff; }
  </style>
</head>
<body>
  <nav class="navbar navbar-expand-lg py-4">
    <div class="container">
      <a class="navbar-brand fw-bold fs-4" href="/">WebGlow AI</a>
      <div class="d-flex"><a href="/contact" class="btn btn-outline-dark rounded-pill px-4">Contact</a></div>
    </div>
  </nav>

  <header class="hero text-center">
    <div class="container" data-aos="fade-up">
      <h1 class="display-3 fw-bold mb-4">Build Your <span style="color: var(--primary);">AI Website</span> In Seconds</h1>
      <p class="lead mb-5 opacity-75">No coding. No design skills. Just enter your business name and watch the magic happen.</p>
      <a href="/build-with-ai" class="btn btn-ai btn-lg">Start Building with AI ✨</a>
    </div>
  </header>

  <section class="py-5 text-center">
    <div class="container">
        <div class="row g-4 justify-content-center">
            <div class="col-md-4">
                <div class="p-4 bg-white rounded-4 shadow-sm h-100">
                    <h4 class="fw-bold">Industry Specific</h4>
                    <p class="opacity-75">Tailored content for plumbers, lawyers, restaurants, and more.</p>
                </div>
            </div>
             <div class="col-md-4">
                <div class="p-4 bg-white rounded-4 shadow-sm h-100">
                    <h4 class="fw-bold">Instant Preview</h4>
                    <p class="opacity-75">See your website live on Vercel immediately after generation.</p>
                </div>
            </div>
        </div>
    </div>
  </section>

  <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/aos/2.3.4/aos.js"></script>
  <script>AOS.init();</script>
</body>
</html>
"""

BUILD_WITH_AI_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Build Your AI Website | WebGlow</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    * { font-family: 'Inter', -apple-system, sans-serif; }
    body { 
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
      min-height: 100vh; 
      display: flex; 
      align-items: center; 
      justify-content: center; 
      padding: 20px;
    }
    .form-box { 
      background: rgba(255, 255, 255, 0.95); 
      padding: 48px; 
      border-radius: 24px; 
      box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); 
      width: 100%; 
      max-width: 560px; 
      backdrop-filter: blur(10px);
    }
    .form-box h2 {
      font-weight: 800;
      font-size: 2rem;
      margin-bottom: 0.5rem;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .form-box .subtitle {
      color: #6b7280;
      margin-bottom: 2rem;
      font-size: 1rem;
    }
    .form-label { 
      font-weight: 600; 
      color: #374151;
      font-size: 0.875rem;
      margin-bottom: 0.5rem;
    }
    .form-control, .form-select {
      border: 2px solid #e5e7eb;
      border-radius: 12px;
      padding: 14px 16px;
      font-size: 1rem;
      transition: all 0.2s;
    }
    .form-control:focus, .form-select:focus {
      border-color: #667eea;
      box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.1);
    }
    .btn-generate {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border: none;
      color: white;
      padding: 16px 32px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 1.1rem;
      width: 100%;
      transition: all 0.3s ease;
      margin-top: 1rem;
    }
    .btn-generate:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
    }
    .feature-pills {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 1.5rem;
    }
    .feature-pill {
      background: #f3f4f6;
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 0.75rem;
      color: #6b7280;
      font-weight: 500;
    }
    .loader { 
      display: none; 
      position: fixed; 
      top: 0; 
      left: 0; 
      width: 100%; 
      height: 100%; 
      background: rgba(255,255,255,0.98); 
      z-index: 1000; 
      flex-direction: column; 
      align-items: center; 
      justify-content: center; 
    }
    .spinner {
      width: 60px;
      height: 60px;
      border: 4px solid #f3f4f6;
      border-top-color: #667eea;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .loader h4 {
      margin-top: 1.5rem;
      color: #374151;
      font-weight: 600;
    }
    .loader p {
      color: #6b7280;
      font-size: 0.875rem;
    }
  </style>
</head>
<body>
  <div class="form-box">
    <div class="text-center">
      <h2>Build Your AI Website</h2>
      <p class="subtitle">Get a stunning, unique website in seconds</p>
      <div class="feature-pills justify-content-center">
        <span class="feature-pill">✨ AI-Powered</span>
        <span class="feature-pill">🎨 Unique Design</span>
        <span class="feature-pill">⚡ Instant Preview</span>
      </div>
    </div>
    
    <form id="ai-form">
      <div class="mb-3">
        <label class="form-label">Business Name</label>
        <input type="text" id="businessName" class="form-control" placeholder="e.g. Smith's Plumbing" required>
      </div>
      
      <div class="mb-3">
        <label class="form-label">Industry</label>
        <select id="businessType" class="form-select" required>
          <option value="">Select your industry...</option>
          <option value="business">Business / Consulting</option>
          <option value="agency">Creative Agency</option>
          <option value="portfolio">Personal Portfolio</option>
          <option value="ecommerce">E-commerce / Retail</option>
          <option value="plumber">Plumbing / HVAC</option>
          <option value="lawyer">Legal Services</option>
          <option value="restaurant">Restaurant / Cafe</option>
          <option value="fitness">Fitness / Gym</option>
          <option value="realestate">Real Estate</option>
        </select>
      </div>
      
      <div class="mb-3">
        <label class="form-label">Services You Offer</label>
        <textarea id="services" class="form-control" rows="3" required placeholder="e.g. Emergency Repairs, Installation, Maintenance, Consultation..."></textarea>
      </div>
      
      <div class="mb-3">
        <label class="form-label">Design Style</label>
        <select id="designStyle" class="form-select" required>
          <option value="modern">Modern - Sleek & Futuristic</option>
          <option value="professional">Professional - Corporate & Trustworthy</option>
          <option value="creative">Creative - Bold & Vibrant</option>
          <option value="minimal">Minimal - Elegant & Simple</option>
        </select>
      </div>
      
      <div class="mb-4">
        <label class="form-label">Location</label>
        <input type="text" id="location" class="form-control" placeholder="e.g. London, UK" required>
      </div>
      
      <button type="submit" class="btn btn-generate">Generate My Website ✨</button>
    </form>
  </div>

  <div class="loader" id="loader">
    <div class="spinner"></div>
    <h4 id="statusText">Designing your website...</h4>
    <p>Our AI is crafting a unique design just for you</p>
  </div>

  <script>
    const statusMessages = [
      "Designing your website...",
      "Creating unique layout...",
      "Writing compelling content...",
      "Adding stunning visuals...",
      "Finalizing your preview..."
    ];
    let messageIndex = 0;
    
    document.getElementById('ai-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      document.getElementById('loader').style.display = 'flex';
      
      // Rotate status messages
      const statusInterval = setInterval(() => {
        messageIndex = (messageIndex + 1) % statusMessages.length;
        document.getElementById('statusText').textContent = statusMessages[messageIndex];
      }, 3000);
      
      const payload = {
        businessName: document.getElementById('businessName').value,
        businessType: document.getElementById('businessType').value,
        services: document.getElementById('services').value,
        location: document.getElementById('location').value,
        style: document.getElementById('designStyle').value
      };

      try {
        const res = await fetch('/api/generate-site', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        clearInterval(statusInterval);
        
        if(data.success) {
          if(data.previewUrl) {
            window.location.href = data.previewUrl;
          } else {
            // Poll for status
            checkStatus(data.slug);
          }
        } else {
          alert("Error: " + data.message);
          document.getElementById('loader').style.display = 'none';
        }
      } catch (err) {
        clearInterval(statusInterval);
        alert("Failed to connect to server.");
        document.getElementById('loader').style.display = 'none';
      }
    });
    
    async function checkStatus(slug) {
      try {
        const res = await fetch('/api/status/' + slug);
        const data = await res.json();
        document.getElementById('statusText').textContent = data.message;
        
        if(data.status === 'COMPLETED' && data.previewUrl) {
          window.location.href = data.previewUrl;
        } else if(data.status === 'FAILED') {
          alert('Generation failed: ' + data.message);
          document.getElementById('loader').style.display = 'none';
        } else {
          setTimeout(() => checkStatus(slug), 2000);
        }
      } catch(e) {
        setTimeout(() => checkStatus(slug), 2000);
      }
    }
  </script>
</body>
</html>
"""

HOSTING_SETUP_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Launching Your Website</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #000; color: #fff; height: 100vh; display: flex; align-items: center; justify-content: center; overflow: hidden; font-family: sans-serif; }
        .progress-circle { width: 150px; height: 150px; border: 4px solid rgba(110,142,251,0.1); border-top-color: #6e8efb; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 30px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .status-card { background: rgba(255,255,255,0.05); padding: 30px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); width: 100%; max-width: 500px; text-align: center; }
    </style>
</head>
<body>
    <div class="status-card">
        <div class="progress-circle"></div>
        <h2 id="title">Deploying Your Website...</h2>
        <p class="opacity-50">Activating your real hosting on WebGlow.</p>
        <div id="success" style="display:none">
            <h1 class="text-success mb-4">Live! ✨</h1>
            <a href="#" id="liveBtn" class="btn btn-primary btn-lg rounded-pill px-5">Visit Website</a>
        </div>
    </div>

    <script>
        const slug = window.location.pathname.split('/').pop();
        async function activate() {
            try {
                const res = await fetch(`/api/hosting/activate/${slug}`, { method: 'POST' });
                const data = await res.json();
                if(data.success) {
                    document.querySelector('.progress-circle').style.display = 'none';
                    document.getElementById('title').style.display = 'none';
                    document.getElementById('success').style.display = 'block';
                    document.getElementById('liveBtn').href = `/generated-sites/${slug}/index.html`;
                }
            } catch (e) { console.error(e); }
        }
        setTimeout(activate, 2000);
    </script>
</body>
</html>
"""

# --- REMOTE FETCH UTILS REMOVED - AI ONLY MODE ---
# Old template system completely removed

@app.route('/')
def home():
    return render_template_string(INDEX_HTML)

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
            "templates": os.path.exists(TEMPLATES_DIR)
        },
        "ls": {
            "task": os.listdir("/var/task") if os.path.exists("/var/task") else [],
            "project_root": os.listdir(PROJECT_ROOT) if os.path.exists(PROJECT_ROOT) else []
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
        "github_base": GITHUB_RAW_BASE,
        "local_path": local_path,
        "exists_locally": exists,
        "github_status": status,
        "project_root": PROJECT_ROOT
    })

@app.route('/build-with-ai')
def build_with_ai_page():
    ensure_file('build-with-ai.html')
    return send_from_directory(PROJECT_ROOT, 'build-with-ai.html')

@app.route('/dashboard')
def dashboard():
    ensure_file('dashboard.html')
    return send_from_directory(PROJECT_ROOT, "dashboard.html")

@app.route('/contact')
def contact_page():
    ensure_file('contact.html')
    return send_from_directory(PROJECT_ROOT, 'contact.html')

@app.route('/about')
def about_page():
    ensure_file('about.html')
    return send_from_directory(PROJECT_ROOT, 'about.html')

@app.route('/services')
def services_page():
    ensure_file('services.html')
    return send_from_directory(PROJECT_ROOT, 'services.html')

@app.route('/hosting/setup/<slug>')
def hosting_setup(slug):
    return render_template_string(HOSTING_SETUP_HTML)


@app.route('/api/plans')
def get_plans():
    return jsonify([
        {"id": "basic", "name": "Basic", "price": "£9/mo", "features": ["1 Website", "Standard Speed", "Basic SEO"]},
        {"id": "pro", "name": "Pro", "price": UK_PRICE_SYMBOL + "19/mo", "features": ["5 Websites", "Ultra Fast", "Advanced SEO"]},
        {"id": "business", "name": "Business", "price": UK_PRICE_SYMBOL + "49/mo", "features": ["Unlimited Sites", "Priority Support", "Email Included"]}
    ])

# Use a global symbol for price if needed
UK_PRICE_SYMBOL = "£"

@app.route('/api/hosting/activate/<slug>', methods=['POST'])
def activate_hosting(slug):
    site_dir = os.path.join(GENERATED_DIR, slug)
    if not os.path.exists(site_dir): return jsonify({"success": False, "message": "Site not found"}), 404
    
    # Simulate activation
    with open(os.path.join(site_dir, ".active"), "w") as f:
        f.write("active")
        
    # REAL HOSTING LAUNCH: 
    # Overwrite the preview wrapper with the actual site content
    demo_index = os.path.join(site_dir, "demo", "index.html")
    root_index = os.path.join(site_dir, "index.html")
    
    if os.path.exists(demo_index):
        with open(demo_index, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Optional: Add a subtle "Hosted by WebGlow" banner
        live_badge = """
        <div id="webglow-live-badge" style="position: fixed; bottom: 20px; right: 20px; background: rgba(0,0,0,0.8); color: #fff; padding: 10px 20px; border-radius: 30px; font-family: sans-serif; font-size: 12px; z-index: 9999; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1);">
            <span style="color: #6e8efb;">●</span> Live on WebGlow
        </div>
        """
        if "</body>" in content:
            content = content.replace("</body>", f"{live_badge}\n</body>")
        else:
            content += live_badge
            
        with open(root_index, 'w', encoding='utf-8') as f:
            f.write(content)
            
    return jsonify({"success": True})

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
    """List all AI-generated sites and their current status."""
    sites = []
    if os.path.exists(GENERATED_DIR):
        for slug in os.listdir(GENERATED_DIR):
            site_path = os.path.join(GENERATED_DIR, slug)
            if not os.path.isdir(site_path): continue
            
            # Status check
            status = "live" if os.path.exists(os.path.join(site_path, ".active")) else "preview"
            
            # Name extraction (from slug)
            name = slug.replace("-", " ").title()
            
            sites.append({
                "slug": slug,
                "name": name,
                "status": status
            })
    return jsonify(sites)

@app.route('/generated-sites/<path:path>')
def serve_generated_site(path):
    """Serve AI-generated sites only - NO template fallback."""
    local_target = os.path.join(GENERATED_DIR, path)
    if os.path.exists(local_target):
        return send_from_directory(GENERATED_DIR, path)
    
    # If file doesn't exist, return 404 - no template fallback
    return "Not found", 404

@app.route('/src/<path:path>')
def serve_src(path):
    """Serve source assets like CSS, JS, and images."""
    rel_path = f"src/{path}"
    ensure_file(rel_path)
    return send_from_directory(os.path.join(PROJECT_ROOT, 'src'), path)

def generate_custom_site_html(data):
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
        "Centered hero with animated gradient background, services as icon + text tiles"
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
    
    # Select random patterns for this generation
    selected_layout = random.choice(layout_patterns)
    selected_nav = random.choice(nav_patterns)
    selected_anim = random.choice(animation_patterns)
    
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
    
    # Select random variations within the style
    style_config = style_design_systems.get(style, style_design_systems["modern"])
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

COLOR PALETTE: {selected_colors}
TYPOGRAPHY: {selected_typography}
VISUAL EFFECTS: {selected_effects}

SERVICES TO FEATURE: {', '.join(services_list)}

---
REQUIRED SECTIONS:
---
1. HERO: Full-viewport or oversized hero with:
   - Unique, benefit-driven headline (NOT generic "Welcome to")
   - Compelling subheadline about their specific services in {location}
   - Strong CTA button
   - Background: gradient, subtle pattern, or carefully selected image placeholder

2. SERVICES SECTION: Use this layout pattern: {selected_layout}
   - Showcase these services: {', '.join(services_list)}
   - Each service needs: icon (FontAwesome), title, 2-sentence description
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
- Use unexpected spacing, asymmetric layouts, creative visual hierarchies
- Each element should feel considered and custom-designed
- No lorem ipsum — write real, compelling copy specific to {business_type} in {location}
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
                response = model.generate_content(prompt, generation_config=generation_config)
                html_code = response.text.strip()
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
            return html_code
            
        except Exception as e:
            print(f"Attempt {attempt + 1} error: {e}")
            if attempt == max_retries - 1:
                print("AI generation failed with exception")
                return None
    
    return None


def generate_unique_site(data):
    """Generate a unique, modern website programmatically when AI is unavailable.
    
    This creates a completely custom site with randomized design elements.
    """
    import random
    
    business_name = data.get('businessName', 'My Business')
    business_type = data.get('businessType', 'business')
    location = data.get('location', 'Your Area')
    services = data.get('services', 'Expert Services')
    style = data.get('style', 'modern')
    
    services_list = [s.strip() for s in services.split(',') if s.strip()][:4]
    if len(services_list) < 2:
        services_list = ['Professional Service', 'Expert Solutions', 'Quality Care']
    
    # Random design variations for uniqueness
    hues = [220, 260, 280, 320, 340, 200, 240, 300]  # Different color hues
    hue1 = random.choice(hues)
    hue2 = (hue1 + random.randint(30, 60)) % 360
    
    # Random layout patterns
    hero_patterns = ['split', 'centered', 'asymmetric']
    card_patterns = ['grid', 'masonry', 'horizontal']
    
    selected_hero = random.choice(hero_patterns)
    selected_cards = random.choice(card_patterns)
    
    # Generate unique service cards
    service_cards = ""
    icons = ['fa-star', 'fa-gem', 'fa-bolt', 'fa-heart', 'fa-rocket', 'fa-shield-alt', 'fa-trophy', 'fa-crown']
    random.shuffle(icons)
    
    for i, svc in enumerate(services_list):
        delay = i * 0.1
        icon = icons[i % len(icons)]
        service_cards += f'''
        <div class="service-card" style="animation-delay: {delay}s">
            <div class="service-icon"><i class="fas {icon}"></i></div>
            <h3>{svc}</h3>
            <p>Expert {svc.lower()} services in {location}. We deliver professional results with attention to detail and customer satisfaction.</p>
        </div>'''
    
    # Unique CSS based on selected style
    if style == 'modern':
        bg_color = '#0a0a0a'
        text_color = '#fafafa'
        accent_gradient = f'linear-gradient(135deg, hsl({hue1}, 80%, 60%) 0%, hsl({hue2}, 80%, 60%) 100%)'
    elif style == 'professional':
        bg_color = '#fafafa'
        text_color = '#1a1a1a'
        accent_gradient = f'linear-gradient(135deg, hsl({hue1}, 60%, 40%) 0%, hsl({hue2}, 60%, 35%) 100%)'
    elif style == 'creative':
        bg_color = f'hsl({hue1}, 20%, 8%)'
        text_color = '#ffffff'
        accent_gradient = f'linear-gradient(135deg, hsl({hue1}, 90%, 60%) 0%, hsl({hue2}, 90%, 60%) 50%, hsl({(hue1+120)%360}, 90%, 60%) 100%)'
    else:  # minimal
        bg_color = '#ffffff'
        text_color = '#1a1a1a'
        accent_gradient = f'linear-gradient(135deg, hsl({hue1}, 70%, 50%) 0%, hsl({hue1}, 70%, 40%) 100%)'
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{business_name} | {business_type.title()} in {location}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {{
            --bg: {bg_color};
            --text: {text_color};
            --accent: {accent_gradient};
            --surface: rgba(128,128,128,0.1);
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
        nav {{ position: fixed; top: 0; left: 0; right: 0; padding: 1.5rem 5%; display: flex; justify-content: space-between; align-items: center; z-index: 1000; background: rgba(255,255,255,0.05); backdrop-filter: blur(10px); }}
        .logo {{ font-size: 1.5rem; font-weight: 800; background: var(--accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .nav-links {{ display: flex; gap: 2rem; list-style: none; }}
        .nav-links a {{ color: var(--text); opacity: 0.7; text-decoration: none; font-weight: 500; transition: opacity 0.3s; }}
        .nav-links a:hover {{ opacity: 1; }}
        .nav-cta {{ padding: 0.75rem 1.5rem; background: var(--accent); color: white; text-decoration: none; border-radius: 50px; font-weight: 600; }}
        
        .hero {{ min-height: 100vh; display: flex; align-items: center; padding: 8rem 5% 4rem; }}
        .hero-content {{ max-width: 600px; }}
        .hero h1 {{ font-size: clamp(2.5rem, 5vw, 4rem); font-weight: 800; line-height: 1.1; margin-bottom: 1.5rem; }}
        .hero h1 span {{ background: var(--accent); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .hero p {{ font-size: 1.25rem; opacity: 0.8; margin-bottom: 2rem; }}
        .hero-cta {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
        .btn-primary {{ padding: 1rem 2rem; background: var(--accent); color: white; text-decoration: none; border-radius: 50px; font-weight: 600; display: inline-flex; align-items: center; gap: 0.5rem; }}
        .btn-secondary {{ padding: 1rem 2rem; background: transparent; color: var(--text); text-decoration: none; border-radius: 50px; font-weight: 600; border: 1px solid rgba(128,128,128,0.3); }}
        
        .services {{ padding: 6rem 5%; }}
        .section-header {{ text-align: center; max-width: 600px; margin: 0 auto 4rem; }}
        .section-header h2 {{ font-size: clamp(2rem, 4vw, 3rem); font-weight: 700; margin-bottom: 1rem; }}
        .services-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 2rem; max-width: 1200px; margin: 0 auto; }}
        .service-card {{ background: var(--surface); border-radius: 20px; padding: 2.5rem; border: 1px solid rgba(128,128,128,0.1); transition: transform 0.3s, box-shadow 0.3s; opacity: 0; animation: fadeUp 0.6s forwards; }}
        .service-card:hover {{ transform: translateY(-10px); box-shadow: 0 20px 40px rgba(0,0,0,0.1); }}
        @keyframes fadeUp {{ to {{ opacity: 1; transform: translateY(0); }} from {{ opacity: 0; transform: translateY(30px); }} }}
        .service-icon {{ width: 60px; height: 60px; background: var(--accent); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; color: white; margin-bottom: 1.5rem; }}
        .service-card h3 {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 0.75rem; }}
        .service-card p {{ opacity: 0.7; font-size: 0.95rem; }}
        
        .about {{ padding: 6rem 5%; background: var(--surface); }}
        .about-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; max-width: 1200px; margin: 0 auto; }}
        .about-content h2 {{ font-size: clamp(2rem, 4vw, 2.5rem); font-weight: 700; margin-bottom: 1.5rem; }}
        .about-content p {{ opacity: 0.8; margin-bottom: 1.5rem; font-size: 1.1rem; line-height: 1.8; }}
        .features {{ display: flex; flex-direction: column; gap: 1rem; }}
        .feature {{ display: flex; align-items: center; gap: 1rem; }}
        
        .contact {{ padding: 6rem 5%; text-align: center; }}
        .contact-box {{ max-width: 600px; margin: 0 auto; background: var(--surface); border-radius: 24px; padding: 3rem; }}
        .contact h2 {{ font-size: clamp(2rem, 4vw, 2.5rem); margin-bottom: 1rem; }}
        .contact p {{ opacity: 0.8; margin-bottom: 2rem; }}
        .contact-info {{ display: flex; flex-direction: column; gap: 1rem; margin-top: 2rem; }}
        
        footer {{ padding: 2rem 5%; text-align: center; opacity: 0.6; border-top: 1px solid rgba(128,128,128,0.1); }}
        
        @media (max-width: 968px) {{
            .hero-grid, .about-grid {{ grid-template-columns: 1fr; text-align: center; }}
            .nav-links {{ display: none; }}
        }}
    </style>
</head>
<body>
    <nav>
        <div class="logo">{business_name}</div>
        <ul class="nav-links">
            <li><a href="#services">Services</a></li>
            <li><a href="#about">About</a></li>
            <li><a href="#contact">Contact</a></li>
        </ul>
        <a href="#contact" class="nav-cta">Get Started</a>
    </nav>

    <section class="hero">
        <div class="hero-content">
            <h1>Premium {business_type.title()} <span>in {location}</span></h1>
            <p>Experience exceptional {services_list[0]} and more with {business_name}. Professional services tailored to your needs.</p>
            <div class="hero-cta">
                <a href="#contact" class="btn-primary">Get Free Quote <i class="fas fa-arrow-right"></i></a>
                <a href="#services" class="btn-secondary">Our Services</a>
            </div>
        </div>
    </section>

    <section class="services" id="services">
        <div class="section-header">
            <h2>Our Services</h2>
            <p>Comprehensive {business_type} solutions for {location}</p>
        </div>
        <div class="services-grid">
            {service_cards}
        </div>
    </section>

    <section class="about" id="about">
        <div class="about-grid">
            <div class="about-content">
                <h2>Why Choose {business_name}?</h2>
                <p>Based in {location}, we deliver excellence in {services_list[0].lower()}. Our team combines expertise with dedication.</p>
                <div class="features">
                    <div class="feature"><i class="fas fa-check-circle" style="color: hsl({hue1}, 80%, 60%);"></i><span>Licensed & Insured Professionals</span></div>
                    <div class="feature"><i class="fas fa-check-circle" style="color: hsl({hue1}, 80%, 60%);"></i><span>Transparent Pricing</span></div>
                    <div class="feature"><i class="fas fa-check-circle" style="color: hsl({hue1}, 80%, 60%);"></i><span>Fast & Reliable Service</span></div>
                </div>
            </div>
        </div>
    </section>

    <section class="contact" id="contact">
        <div class="contact-box">
            <h2>Ready to Get Started?</h2>
            <p>Contact {business_name} today for a free consultation in {location}.</p>
            <a href="mailto:contact@{business_name.lower().replace(' ', '')}.com" class="btn-primary">
                <i class="fas fa-envelope"></i> Contact Us
            </a>
        </div>
    </section>

    <footer>
        <p>&copy; {datetime.datetime.now().year} {business_name}. All rights reserved. | {business_type.title()} Services in {location}</p>
    </footer>

    <script>
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {{
            anchor.addEventListener('click', function (e) {{
                e.preventDefault();
                document.querySelector(this.getAttribute('href')).scrollIntoView({{ behavior: 'smooth' }});
            }});
        }});
    </script>
</body>
</html>'''
    
    return html


# Remove the old fallback template system entirely
def generate_fallback_site(data, demo_dir):
    """DEPRECATED: No longer used."""
    return False

@app.route('/api/generate-site', methods=['POST'])
def generate_site():
    data = request.json
    business_name = data.get('businessName', 'My Business')
    site_slug = business_name.lower().replace(" ", "-").replace("'", "").replace("\"", "")
    
    # 1. Initialize Progress
    PROGRESS_STORE[site_slug] = {"status": "AI_CODE_GEN", "message": "AI is coding your professional website..."}
    
    # Capture request context for the background thread
    request_host_url = request.host_url.rstrip("/")

    def run_generation():
        try:
            base_url = request_host_url
            # 2. FORCE AI TO CODE FROM SCRATCH
            PROGRESS_STORE[site_slug]["message"] = "AI Architect is designing your layout..."
            custom_html = generate_custom_site_html(data)

            # 3. Setup Directory Structure
            PROGRESS_STORE[site_slug]["message"] = "Building your bespoke file structure..."
            site_path = os.path.join(GENERATED_DIR, site_slug)
            if os.path.exists(site_path): shutil.rmtree(site_path)
            os.makedirs(site_path, exist_ok=True)
            demo_dir = os.path.join(site_path, "demo")
            os.makedirs(demo_dir, exist_ok=True)

            if not custom_html:
                # AI failed - use unique programmatic fallback
                PROGRESS_STORE[site_slug]["message"] = "Using smart fallback generator..."
                custom_html = generate_unique_site(data)
                
            if not custom_html:
                PROGRESS_STORE[site_slug] = {"status": "FAILED", "message": "Failed to generate website."}
                return
            
            # 4. Save the AI-generated Code
            with open(os.path.join(demo_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(str(custom_html))

            # 5. Create the Preview Wrapper
            PROGRESS_STORE[site_slug]["message"] = "Finalizing your professional preview..."
            
            preview_bar_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Preview - {business_name}</title>
    <style>
        body {{ margin: 0; padding: 0; overflow: hidden; font-family: 'Inter', sans-serif; background: #000; }}
        .bar {{ min-height: 70px; background: #111; color: #fff; display: flex; align-items: center; justify-content: space-between; padding: 0 32px; border-bottom: 1px solid rgba(255,255,255,0.1); z-index: 1000; position: relative; }}
        .brand {{ display: flex; flex-direction: column; }}
        .brand strong {{ font-size: 20px; letter-spacing: -0.5px; color: #fff; }}
        .brand span {{ font-size: 11px; color: #aaa; text-transform: uppercase; font-weight: 700; letter-spacing: 1px; }}
        .conversion-msg {{ background: rgba(255,255,255,0.05); padding: 8px 16px; border-radius: 40px; border: 1px solid rgba(255,255,255,0.1); font-size: 13px; color: #eee; display: flex; align-items: center; gap: 8px; }}
        .conversion-msg b {{ color: #6e8efb; }}
        .bar-actions {{ display: flex; gap: 12px; align-items: center; }}
        .btn {{ padding: 12px 24px; border-radius: 40px; text-decoration: none; font-weight: 700; font-size: 14px; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); border: none; cursor: pointer; display: flex; align-items: center; gap: 8px; }}
        .btn-launch {{ background: linear-gradient(135deg, #6e8efb, #a777e3); color: #fff; box-shadow: 0 4px 15px rgba(110, 142, 251, 0.4); }}
        .btn-launch:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(110, 142, 251, 0.6); }}
        .btn-download {{ background: rgba(255,255,255,0.1); color: #fff; border: 1px solid rgba(255,255,255,0.1); }}
        .btn-download:hover {{ background: rgba(255,255,255,0.2); }}
        iframe {{ width: 100%; height: calc(100vh - 70px); border: none; }}
        .modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 10001; align-items: center; justify-content: center; backdrop-filter: blur(10px); }}
        .modal-content {{ background: white; padding: 40px; border-radius: 30px; max-width: 900px; width: 90%; color: #333; }}
        .close-modal {{ float: right; font-size: 32px; cursor: pointer; }}
        .plans-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 30px; margin-top: 30px; }}
        .plan-card {{ border: 1px solid #eee; padding: 30px; border-radius: 20px; text-align: center; transition: all 0.3s; }}
        .plan-card:hover {{ transform: translateY(-5px); border-color: #6e8efb; }}
        .price {{ font-size: 32px; font-weight: 800; color: #6e8efb; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="bar">
        <div class="brand">
            <strong>{business_name}</strong>
            <span>AI Generated Preview</span>
        </div>
        <div class="conversion-msg">
            ✨ <span>Your website is ready! <b>Our team can finalise and launch it for you for FREE.</b></span>
        </div>
        <div class="bar-actions">
            <button onclick="openModal()" class="btn btn-launch">🚀 Go Live Now</button>
            <a href="{base_url}/download/{site_slug}" class="btn btn-download">Download Files</a>
        </div>
    </div>
    
    <iframe src="demo/index.html" title="{business_name} preview"></iframe>

    <div class="modal-overlay" id="plansModal">
        <div class="modal-content">
            <span class="close-modal" onclick="closeModal()">&times;</span>
            <h2 style="text-align: center; margin: 0; font-size: 32px;">Go Live in Seconds</h2>
            <p style="text-align: center; color: #666; margin-top: 10px;">Pick a hosting plan to publish <strong>{business_name}</strong> to a custom domain.</p>
            
            <div class="plans-grid" id="plansGrid">
                <!-- Plans injected by JS -->
            </div>
        </div>
    </div>

    <script>
        function openModal() {{
            document.getElementById('plansModal').style.display = 'flex';
            fetchPlans();
        }}
        function closeModal() {{
            document.getElementById('plansModal').style.display = 'none';
        }}
        async function fetchPlans() {{
            const res = await fetch('/api/plans');
            const plans = await res.json();
            const grid = document.getElementById('plansGrid');
            grid.innerHTML = plans.map(p => `
                <div class="plan-card">
                    <h3>\${{p.name}}</h3>
                    <div class="price">\${{p.price}}</div>
                    <ul style="list-style: none; padding: 0; margin-bottom: 25px; text-align: left;">
                        \${{p.features.map(f => \`<li style="margin-bottom: 10px; font-size: 14px;">✅ \${{f}}</li>\`).join('')}}
                    </ul>
                    <a href="/hosting/setup/{site_slug}?plan=\${{p.id}}" style="padding: 15px 30px; background: #111; color: white; border-radius: 40px; text-decoration: none; font-weight: 700; display: inline-block;">Select Plan</a>
                </div>
            `).join('');
        }}
    </script>
</body>
</html>"""
            with open(os.path.join(site_path, "index.html"), "w", encoding="utf-8") as f:
                f.write(preview_bar_html)

            # 6. Trigger Deployment
            if not os.getenv("VERCEL"):
                threading.Thread(target=lambda: deploy_to_vercel(site_path, site_slug)).start()

            PROGRESS_STORE[site_slug] = {
                "status": "COMPLETED", 
                "message": "Website generated successfully!", 
                "previewUrl": f"{base_url}/generated-sites/{site_slug}/index.html"
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            PROGRESS_STORE[site_slug] = {"status": "FAILED", "message": f"Generation error: {str(e)}"}

    # Start generation
    request_host_url = request.host_url.rstrip("/")
    
    if os.getenv("VERCEL"):
        # On Vercel, run synchronously to ensure completion before function termination
        run_generation()
        # Return the final result immediately since we waited for it
        result = PROGRESS_STORE.get(site_slug, {})
        if result.get("status") == "COMPLETED":
            return jsonify({
                "success": True, 
                "previewUrl": result.get("previewUrl"), 
                "slug": site_slug
            })
        else:
            return jsonify({
                "success": False, 
                "message": result.get("message", "Generation failed on Vercel.")
            }), 500
    else:
        # Off Vercel, run in background thread for better concurrency
        threading.Thread(target=run_generation).start()
        return jsonify({"success": True, "message": "AI started coding...", "slug": site_slug})


@app.route('/api/status/<slug>')
def get_site_status(slug):
    return jsonify(PROGRESS_STORE.get(slug, {"status": "UNKNOWN", "message": "Waiting..."}))

@app.route('/download/<slug>')
def download_site(slug):
    site_dir = os.path.join(GENERATED_DIR, slug)
    if not os.path.exists(site_dir): return "Not found", 404
    
    temp_dir = tempfile.gettempdir()
    zip_path = os.path.join(temp_dir, f"{slug}_website")
    final_zip = shutil.make_archive(zip_path, 'zip', site_dir)
    
    return send_from_directory(temp_dir, os.path.basename(final_zip), as_attachment=True)

if __name__ == '__main__':
    print("Starting AI Website Builder backend on http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)
