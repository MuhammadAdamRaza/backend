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
  <link rel="shortcut icon" type="image/png" href="src/assets/images/logos/favicon.svg" />
  <link rel="stylesheet" href="src/assets/libs/owl.carousel/dist/assets/owl.carousel.min.css">
  <link rel="stylesheet" href="src/assets/libs/aos-master/dist/aos.css">
  <link rel="stylesheet" href="src/assets/css/styles.css" />
  <link rel="stylesheet" href="src/assets/css/premium.css" />
</head>

<body>

  <!-- Header -->
  <header class="header position-fixed start-0 top-0 w-100">
    <div class="container">
      <nav class="navbar navbar-expand-xl rounded-pill p-7">
        <div class="d-flex align-items-center justify-content-between w-100">
          <a href="index.html" class="logo">
            <img src="src/assets/images/logos/logo-dark.svg" class="img-fluid logo-img" alt="Logo" />
          </a>
          <button class="navbar-toggler border-0 p-0 shadow-none" type="button" data-bs-toggle="offcanvas"
            data-bs-target="#offcanvasHeader" aria-controls="offcanvasHeader">
            <iconify-icon icon="solar:hamburger-menu-bold" class="fs-8 text-dark"></iconify-icon>
          </button>
          <div class="collapse navbar-collapse" id="navbarSupportedContent">
            <ul class="navbar-nav mx-auto gap-2 p-1 bg-light rounded-pill">
              <li class="nav-item">
                <a class="nav-link scroll-link py-2 px-3 rounded-pill fw-medium" href="index.html#aboutus">About Us</a>
              </li>
              <li class="nav-item">
                <a class="nav-link scroll-link py-2 px-3 rounded-pill fw-medium" href="index.html#services">Services</a>
              </li>
              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle py-2 px-3 rounded-pill fw-medium" href="index.html#work" role="button" data-bs-toggle="dropdown" aria-expanded="false">
                  Templates
                </a>
                <ul class="dropdown-menu border-0 shadow-sm dropdown-menu-custom">
                  <li><a class="dropdown-item" href="index.html#work">All Templates</a></li>
                  <li><hr class="dropdown-divider"></li>
                  <li><a class="dropdown-item" href="templates/business/index.html">Business</a></li>
                  <li><a class="dropdown-item" href="templates/agency/index.html">Agency</a></li>
                  <li><a class="dropdown-item" href="templates/portfolio/index.html">Portfolio</a></li>
                  <li><a class="dropdown-item" href="templates/e-commerce/index.html">E-commerce</a></li>
                  <li><a class="dropdown-item" href="templates/services/index.html">Services</a></li>
                </ul>
              </li>


            </ul>
            <div class="d-flex align-items-center">
              <a href="contact.html" class="btn btn-dark px-4 py-2">Contact</a>
            </div>
          </div>
        </div>
      </nav>
    </div>
  </header>

  <!--  Page Wrapper -->
  <div class="page-wrapper overflow-hidden">

    <!--  Banner Section -->
    <section class="banner-section bg-gradient-shaph position-relative pt-14 pt-md-15 pb-11 pb-lg-12 pb-xl-13">
      <div class="container position-relative z-3">
        <div class="d-flex flex-column gap-10">
          <h1 class="text-center mb-0" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">
            Download Free <em class="font-instrument fw-normal"> Website Templates</em>
          </h1>
          <div class="row justify-content-center" data-aos="fade-up" data-aos-delay="200" data-aos-duration="1000">
            <div class="col-xl-6">
              <p class="text-center mb-0">Get a professional website” no coding, no hassle, no cost.<br><br>
                Just choose a template, download it, and start building. It’s that simple.<br><br>

                Whether it’s for a business, portfolio, blog, or online store, our templates are ready to go
                immediately after download..</p>
            </div>
          </div>
          <div class="d-flex flex-column align-items-center justify-content-center gap-3" data-aos="fade-up"
            data-aos-delay="300" data-aos-duration="1000">
            <div class="d-md-flex align-items-center justify-content-center gap-10">
              <a href="#work" class="btn btn-primary py-md-8 pe-md-14 mx-auto mx-md-0 d-block d-md-flex">
                <span class="btn-text">View Templates</span>
                <iconify-icon icon="solar:arrow-right-up-linear"
                  class="btn-icon bg-white text-dark round-32 rounded-circle hstack justify-content-center fs-6"></iconify-icon>
              </a>
            </div>
            <a href="/build-with-ai?type=business" class="btn btn-primary py-md-8 pe-md-14 mx-auto mx-md-0 d-block d-md-flex">
              <span class="btn-text">Build With Ai</span>
              <iconify-icon icon="solar:magic-stick-3-linear"
                class="btn-icon bg-white text-dark round-32 rounded-circle hstack justify-content-center fs-6"></iconify-icon>
            </a>
          </div>
        </div>
      </div>
    </section>

    <!--  Logo Ipsum Section -->
    <section class="logo-ipsum py-10 py-lg-12 py-xl-13">
      <div class="container position-relative z-3">
        <div class="d-flex flex-column gap-9">
          <div class="row position-relative hstack justify-content-center">
            <div class="col-lg-6">
              <div class="d-flex align-items-center justify-content-between gap-3">
                <hr class="border-2 w-20 d-block">
                <p class="mb-0 text-center flex-sm-shrink-0">Loved by 1000+ big and
                  small
                  brands around the worlds</p>
                <hr class="border-2 w-20 d-block">
              </div>
            </div>
          </div>

          <div class="marquee w-100 d-flex align-items-center overflow-hidden">
            <div class="marquee-content d-flex align-items-center justify-content-between gap-13">
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-1.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-2.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-3.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-4.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-5.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-1.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-2.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-3.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-4.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-5.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-1.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-2.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-3.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-4.svg" alt="logo-ipsum" class="img-fluid">
              </div>
              <div class="marquee-tag hstack justify-content-center">
                <img src="src/assets/images/brands/logo-ipsum-5.svg" alt="logo-ipsum" class="img-fluid">
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>-->

    <!--  Count Section -->
    <section class="py-10 py-lg-12 py-xl-13" id="aboutus">
      <div class="container position-relative z-3">
        <div class="d-flex flex-column gap-10 gap-lg-12">
          <div class="d-flex flex-column gap-3">
            <h2 class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">Clean HTML &
              CSS, easy to edit</h2>
            <p class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">Just download
              the template you like and start building. No catch, no waiting, no design headaches.</p>
            <p class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000"> Every template
              is fully responsive, SEO-friendly, and easy to customise â€” so your site looks perfect on any device.</p>
            <br>
            <h2 class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000"><em
                class="font-instrument">Designs</em> Made With</h2>

            <div class="d-flex flex-wrap align-items-center justify-content-center gap-3" data-aos="fade-up"
              data-aos-delay="200" data-aos-duration="1000">
              <div class="rounded-pill py-1 px-8 hstack gap-7 bg-secondary-subtle">
                <iconify-icon icon="solar:magic-stick-3-linear" class="fs-9 text-secondary"></iconify-icon>
                <h2 class="mb-0 text-secondary font-instrument"><em>Creativity</em></h2>
              </div>
              <div class="rounded-pill py-1 px-8 hstack gap-7 bg-info-subtle">
                <iconify-icon icon="solar:lightbulb-bolt-linear" class="fs-9 text-info"></iconify-icon>
                <h2 class="mb-0 text-info font-instrument"><em>Innovation</em></h2>
              </div>
              <div class="rounded-pill py-1 px-8 hstack gap-7 bg-light-orange">
                <iconify-icon icon="solar:command-linear" class="fs-9 text-orange"></iconify-icon>
                <h2 class="mb-0 text-orange font-instrument"><em>Strategy</em></h2>
              </div>
            </div>
          </div>

        </div>
      </div>
    </section>

    <!--  Innovation Meets Section -->
    <section class="innovation-meets py-10 py-lg-12 py-xl-13" id="services">
      <div class="container">
        <div class="d-flex flex-column gap-10 gap-lg-12">
          <div class="row justify-content-center">
            <div class="col-lg-6 col-xl-4">
              <h2 class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">Where
                innovation meets <em class="font-instrument">aesthetics</em></h2>
            </div>
          </div>
          <div class="d-flex flex-column gap-4">
            <div class="row">
              <div class="col-sm-6 col-md-4 col-lg">
                <div class="card bg-secondary-subtle" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">
                  <div class="card-body d-flex flex-column gap-11">
                    <iconify-icon icon="solar:palette-round-linear" class="fs-9 text-secondary"></iconify-icon>
                    <h4 class="text-secondary mb-0">Brand<br> Strategy</h4>
                  </div>
                </div>
              </div>
              <div class="col-sm-6 col-md-4 col-lg">
                <div class="card bg-info-subtle" data-aos="fade-up" data-aos-delay="200" data-aos-duration="1000">
                  <div class="card-body d-flex flex-column gap-11">
                    <iconify-icon icon="solar:gallery-wide-linear" class="fs-9 text-info"></iconify-icon>
                    <h4 class="text-info mb-0">Digital<br>
                      Marketing</h4>
                  </div>
                </div>
              </div>
              <div class="col-sm-6 col-md-4 col-lg">
                <div class="card bg-light-orange" data-aos="fade-up" data-aos-delay="300" data-aos-duration="1000">
                  <div class="card-body d-flex flex-column gap-11">
                    <iconify-icon icon="solar:magic-stick-3-linear" class="fs-9 text-orange"></iconify-icon>
                    <h4 class="text-orange mb-0">UI/UX<br>
                      Design</h4>
                  </div>
                </div>
              </div>
              <div class="col-sm-6 col-md-4 col-lg">
                <div class="card bg-success-subtle" data-aos="fade-up" data-aos-delay="400" data-aos-duration="1000">
                  <div class="card-body d-flex flex-column gap-11">
                    <iconify-icon icon="solar:chart-linear" class="fs-9 text-success"></iconify-icon>
                    <h4 class="text-success mb-0">Analytics &<br>
                      Reporting</h4>
                  </div>
                </div>
              </div>
              <div class="col-sm-6 col-md-4 col-lg">
                <div class="card bg-danger-subtle" data-aos="fade-up" data-aos-delay="500" data-aos-duration="1000">
                  <div class="card-body d-flex flex-column gap-11">
                    <iconify-icon icon="solar:window-frame-linear" class="fs-9 text-danger"></iconify-icon>
                    <h4 class="text-danger mb-0">Web<br>
                      Development</h4>
                  </div>
                </div>
              </div>
            </div>
            <div class="card bg-dark mb-0">
              <div class="card-body px-lg-5">
                <div class="row align-items-center justify-content-between gap-4 gap-lg-0">
                  <div class="col-lg-4">
                    <h3 class="mb-0 text-white text-center text-lg-start">See Our Work in Action.
                      Start Your Creative Journey with Us!</h3>
                  </div>
                  <div class="col-lg-8">
                    <div
                      class="d-flex flex-wrap align-items-center justify-content-center justify-content-lg-end gap-7">
                      <a href="https://www.webglow.co.uk" target="_blank" class="btn btn-white">
                        <span class="btn-text">Lets Collaborate</span>
                        <iconify-icon icon="solar:arrow-right-up-linear"
                          class="btn-icon bg-dark text-white round-32 rounded-circle hstack justify-content-center fs-6"></iconify-icon>
                      </a>
                      <a href="#" class="btn btn-outline-light">
                        <span class="btn-text">View Portfolio</span>
                        <iconify-icon icon="solar:arrow-right-up-linear"
                          class="btn-icon bg-white text-dark round-32 rounded-circle hstack justify-content-center fs-6"></iconify-icon>
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!--  Work Section -->
    <section class="py-10 py-lg-12 py-xl-13" id="work">
      <div class="container">
        <div class="d-flex flex-column gap-10 gap-lg-12">
          <div class="row justify-content-center">
            <div class="col-lg-8 col-xl-6 text-center">
              <h2 class="mb-0" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">View Our Template <em
                  class="font-instrument">Selection</em></h2>
              <p class="mb-0 mt-4" data-aos="fade-up" data-aos-delay="150" data-aos-duration="1000">Your next website is
                just a click away. Browse our templates and download the perfect design for your project today.</p>
            </div>
          </div>

          <!-- Category Filters -->
          <div class="row justify-content-center mb-4" data-aos="fade-up" data-aos-delay="200" data-aos-duration="1000">
            <div class="col-12 d-flex flex-wrap justify-content-center gap-3">
              <button class="btn filter-btn-custom filter-btn-active filter-btn" data-filter="All">All</button>
              <button class="btn filter-btn-custom filter-btn-dark filter-btn" data-filter="Business">Business</button>
              <button class="btn filter-btn-custom filter-btn-dark filter-btn" data-filter="Agency">Agency</button>
              <button class="btn filter-btn-custom filter-btn-dark filter-btn"
                data-filter="Portfolio">Portfolio</button>
              <button class="btn filter-btn-custom filter-btn-dark filter-btn"
                data-filter="E-commerce">E-commerce</button>
              <button class="btn filter-btn-custom filter-btn-dark filter-btn" data-filter="Services">Services</button>
            </div>
          </div>
          <div class="row">
            <!-- Templates Grid -->
            <div class="row" id="templates-container">
              <!-- Populated dynamically by templates.js -->
            </div>

            <!-- Bottom Call-to-Action -->
            <div class="row g-4">
              <div class="col-md-6">
                <div class="card bg-primary text-white border-0 shadow-lg template-card"
                  style="animation-delay: 100ms;">
                  <div class="card-body text-center py-5 px-6">
                    <h4 class="text-white mb-3">Looking for a Custom Design?</h4>
                    <p class="mb-4">Get a professional, tailored website built by the experts at WebGlow.</p>
                    <a href="https://www.webglow.co.uk" target="_blank"
                      class="btn btn-light rounded-pill fw-bold text-primary px-5">Hire WebGlow</a>
                  </div>
                </div>
              </div>
              <div class="col-md-6">
                <div class="card bg-dark text-white border-0 shadow-lg template-card" style="animation-delay: 200ms;">
                  <div class="card-body text-center py-5 px-6">
                    <iconify-icon icon="solar:rocket-linear" class="fs-1 text-warning mb-3 d-block"></iconify-icon>
                    <h5 class="text-white mb-3">Sponsored by WebGlow</h5>
                    <p class="mb-4 small">Premium Web Development, Marketing, &amp; SEO Services to skyrocket your
                      business.</p>
                    <a href="https://www.webglow.co.uk" target="_blank"
                      class="btn btn-outline-light rounded-pill btn-sm px-5">Learn More</a>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
    </section>

    <!--  Pricing Section -->

    <!--  FAQ Section -->

    <section class="py-10 py-lg-12 py-xl-13">
      <div class="container">
        <div class="d-flex flex-column gap-10 gap-lg-12">
          <div class="row justify-content-center">
            <div class="col-lg-6 col-xl-4">
              <h2 class="mb-0 text-center" data-aos="fade-up" data-aos-delay="100" data-aos-duration="1000">Got
                questions? We have got <em class="font-instrument">answers</em>
              </h2>
            </div>
          </div>
          <div class="accordion accordion-flush d-flex flex-column gap-3" id="accordionExample">
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="100" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseOne" aria-expanded="true" aria-controls="flush-collapseOne">
                  Are your website templates really free?
                </button>
              </h2>
              <div id="flush-collapseOne" class="accordion-collapse collapse show" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  Yes! All our templates are completely free to download. There are no hidden fees or subscriptions.
                </div>
              </div>
            </div>
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="200" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium collapsed" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseTwo" aria-expanded="false" aria-controls="flush-collapseTwo">
                  Do I need to sign up or create an account to download a template?
                </button>
              </h2>
              <div id="flush-collapseTwo" class="accordion-collapse collapse" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  No sign-ups required. Simply click Download and the template is yours instantly.
                </div>
              </div>
            </div>
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="300" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium collapsed" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseThree" aria-expanded="false" aria-controls="flush-collapseThree">
                  Can I use these templates for commercial projects?
                </button>
              </h2>
              <div id="flush-collapseThree" class="accordion-collapse collapse" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  Yes! Most of our templates are free for personal and commercial use. Be sure to check each
                  templates license for specific details.
                </div>
              </div>
            </div>
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="400" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium collapsed" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseFour" aria-expanded="false" aria-controls="flush-collapseFour">
                  Do I need coding experience to use these templates?
                </button>
              </h2>
              <div id="flush-collapseFour" class="accordion-collapse collapse" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  Not at all! Our templates are easy to edit. You can modify text, images, and styles using basic
                  HTML/CSS or with a website builder.
                </div>
              </div>
            </div>
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="500" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium collapsed" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseFive" aria-expanded="false" aria-controls="flush-collapseFive">
                  Are the templates mobile-friendly?
                </button>
              </h2>
              <div id="flush-collapseFive" class="accordion-collapse collapse" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  Absolutely. Every template is fully responsive, so your site will look great on phones, tablets, and
                  desktops.
                </div>
              </div>
            </div>
            <div class="accordion-item border rounded-1 position-relative overflow-hidden" data-aos="fade-up"
              data-aos-delay="600" data-aos-duration="1000">
              <h2 class="accordion-header">
                <button class="accordion-button fs-7 fw-medium collapsed" type="button" data-bs-toggle="collapse"
                  data-bs-target="#flush-collapseSix" aria-expanded="false" aria-controls="flush-collapseSix">
                  How do I get my website online after downloading a template?
                </button>
              </h2>
              <div id="flush-collapseSix" class="accordion-collapse collapse" data-bs-parent="#accordionExample">
                <div class="accordion-body pt-0">
                  After downloading, upload the files to your hosting provider or use a website builder that accepts
                  HTML templates. Your site will be live instantly!
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>



    <!--  Accolades Achievements Section -->
    <section class="py-10 py-lg-12 py-xl-13">
      <div class="container">
        <div class="premium-cta-card px-4 py-11 py-lg-13 py-xl-14">
          <div class="row justify-content-center">
            <div class="col-lg-10 col-xl-8">
              <div class="d-flex flex-column gap-3">
                <div class="d-flex flex-column gap-7 mb-4">
                  <h1 class="display-5 mb-0 text-center fw-bold text-dark">Instant Access. <em
                      class="font-instrument fw-normal text-primary">Zero Waiting.</em>
                  </h1>
                  <p class="mb-0 text-center opacity-75">Every template is fully designed and ready to use.</p>

                  <div class="d-flex flex-column gap-2 mt-4">
                    <p class="mb-0 text-center">Just: Browse our collection</p>
                    <p class="mb-0 text-center">Click Download</p>
                    <p class="mb-0 text-center">Open the files and customise your content</p>
                    <p class="mb-0 text-center text-danger hstack justify-content-center gap-1">
                      <span class="round-4 bg-danger d-inline-block"></span>
                      Upload to your hosting and launch
                    </p>
                  </div>
                </div>

                <a href="#work" class="btn btn-dark mx-auto d-flex align-items-center gap-3">
                  <span class="btn-text">View Templates</span>
                  <iconify-icon icon="solar:arrow-right-up-linear"
                    class="bg-white text-dark round-32 rounded-circle hstack justify-content-center fs-6"></iconify-icon>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

  </div>

  <!--  Footer -->
  <footer class="footer pt-md-11 pt-lg-12 pt-xl-13">
    <div class="container">
      <div class="py-11 py-5 py-lg-12 pb-0 pb-lg-12">
        <div class="row">
          <div class="col-12 col-lg-5 mb-11 mb-lg-0">
            <div class="d-flex flex-column gap-4 me-xl-5">
              <a href="index.html" class="d-block">
                <img src="src/assets/images/logos/logo-dark.svg" alt="logo" class="img-fluid logo-img">
              </a>
              <p class="mb-0">We built FreeWebsiteTemplates.co.uk to offer genuinely useful designs” clean, modern
                layouts that reflect today web standards.
              </p>

            </div>
          </div>



        </div>
      </div>
      <div class="py-4 border-top">
        <p class="mb-0 text-center">A ©2025 FreeWebsiteTemplates. All Rights Reserved</p>
      </div>
    </div>
  </footer>

  <!--  Get Template -->
  <div class="get-template hstack gap-2">
    <a class="bg-primary px-3 py-2 rounded fs-3 fw-semibold text-white" target="_blank"
      href="https://www.webglow.co.uk">Try WebGlow</a>
    <button class="btn bg-primary p-2 round-40 rounded hstack justify-content-center flex-shrink-0" id="scrollToTopBtn">
      <iconify-icon icon="solar:alt-arrow-up-linear" class="fs-7 text-white"></iconify-icon>
    </button>
  </div>

  <!--  Offcanvas -->
  <div class="offcanvas offcanvas-end" tabindex="-1" id="offcanvasHeader" aria-labelledby="offcanvasHeaderLabel">
    <div class="offcanvas-header">
      <a href="index.html" class="logo">
        <img src="src/assets/images/logos/logo-dark.svg" class="img-fluid logo-img" alt="Logo" />
      </a>
      <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
    </div>
    <div class="offcanvas-body">
      <div class="d-flex flex-column gap-4">
        <ul class="navbar-nav">
          <li class="nav-item">
            <a class="nav-link text-dark fw-medium px-2" href="#aboutus">About Us</a>
          </li>
          <li class="nav-item">
            <a class="nav-link text-dark fw-medium px-2" href="#services">Services</a>
          </li>
          <li class="nav-item">
            <a class="nav-link text-dark fw-medium px-2" href="index.html#work">All Templates</a>
          </li>
        </ul>
        <div class="d-flex flex-column">
          <a href="contact.html" class="btn btn-dark px-4 py-2 w-100 justify-content-center">Contact</a>
        </div>
      </div>
    </div>
  </div>


  <script src="src/assets/libs/jquery/dist/jquery.min.js"></script>
  <script src="src/assets/libs/bootstrap/dist/js/bootstrap.bundle.min.js"></script>
  <script src="src/assets/libs/owl.carousel/dist/owl.carousel.min.js"></script>
  <script src="src/assets/libs/aos-master/dist/aos.js"></script>
  <script src="src/assets/js/custom.js"></script>
  <script src="src/assets/js/templates.js"></script>
  <!-- solar icons -->
  <script src="https://cdn.jsdelivr.net/npm/iconify-icon@1.0.8/dist/iconify-icon.min.js"></script>
</body>

</html>
"""

BUILD_WITH_AI_HTML = """
<!doctype html>
<html lang="en">

<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Build Your Website with AI | Free Website Templates</title>
  <link rel="shortcut icon" type="image/png" href="src/assets/images/logos/favicon.svg" />
  <link rel="stylesheet" href="src/assets/libs/owl.carousel/dist/assets/owl.carousel.min.css">
  <link rel="stylesheet" href="src/assets/libs/aos-master/dist/aos.css">
  <link rel="stylesheet" href="src/assets/css/styles.css" />
  <link rel="stylesheet" href="src/assets/css/premium.css" />
  <style>
    .ai-form-container {
      max-width: 900px;
      margin: 100px auto;
      padding: 60px;
      background: rgba(255, 255, 255, 0.7);
      backdrop-filter: blur(20px) saturate(180%);
      border-radius: 40px;
      box-shadow: 0 40px 100px rgba(0, 0, 0, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.4);
    }

    .form-label {
      font-weight: 700;
      color: #1a1a1a;
      margin-bottom: 12px;
      font-size: 0.95rem;
      letter-spacing: -0.01em;
    }

    .form-control, .form-select {
      border-radius: 16px;
      padding: 16px 20px;
      border: 1px solid rgba(0,0,0,0.08);
      background: rgba(255,255,255,0.8);
      transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
      font-size: 1rem;
    }

    .form-control:focus, .form-select:focus {
      border-color: #6e8efb;
      background: #fff;
      box-shadow: 0 0 0 5px rgba(110, 142, 251, 0.15);
      transform: translateY(-1px);
    }

    .btn-generate {
      background: linear-gradient(135deg, #6e8efb, #a777e3, #6e8efb);
      background-size: 200% auto;
      border: none;
      color: white;
      font-weight: 800;
      padding: 20px;
      border-radius: 20px;
      width: 100%;
      margin-top: 30px;
      transition: all 0.5s ease;
      text-transform: uppercase;
      letter-spacing: 1px;
    }

    .btn-generate:hover {
      background-position: right center;
      transform: translateY(-3px) scale(1.01);
      box-shadow: 0 20px 40px rgba(110, 142, 251, 0.4);
    }

    .loading-overlay {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: #fff;
      z-index: 9999;
      justify-content: center;
      align-items: center;
      flex-direction: column;
    }

    .spinner {
      width: 80px;
      height: 80px;
      border: 2px solid #f3f3f3;
      border-top: 2px solid #6e8efb;
      border-radius: 50%;
      animation: spin 0.8s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }

    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    .progress-bar-container {
      width: 100%;
      max-width: 500px;
      height: 6px;
      background: #f0f0f0;
      border-radius: 10px;
      margin-top: 40px;
      overflow: hidden;
      box-shadow: inset 0 1px 3px rgba(0,0,0,0.05);
    }

    .progress-bar-inner {
      width: 0%;
      height: 100%;
      background: linear-gradient(90deg, #6e8efb, #a777e3, #6e8efb);
      background-size: 200% auto;
      animation: gradient 2s linear infinite;
      transition: width 0.5s ease;
    }

    @keyframes gradient {
      0% { background-position: 0% 50%; }
      100% { background-position: 100% 50%; }
    }

    #loadingText {
      font-weight: 800;
      font-size: 2rem;
      letter-spacing: -0.03em;
      margin-bottom: 8px;
      background: linear-gradient(135deg, #1a1a1a, #666);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
  </style>
</head>

<body>
  <!-- Header -->
  <header class="header position-fixed start-0 top-0 w-100" style="z-index: 100;">
    <div class="container">
      <nav class="navbar navbar-expand-xl p-4">
        <div class="d-flex align-items-center justify-content-between w-100">
          <a href="index.html" class="logo">
            <img src="src/assets/images/logos/logo-dark.svg" class="img-fluid logo-img" alt="Logo" style="height: 40px;" />
          </a>
          <a href="index.html" class="btn btn-outline-dark px-4 py-2 rounded-pill fw-bold">Back to Home</a>
        </div>
      </nav>
    </div>
  </header>

  <div class="container">
    <div class="ai-form-container" data-aos="fade-up">
      <h2 class="text-center mb-3 display-5 fw-bold"><span style="color: #6e8efb;">AI</span> Web Architect</h2>
      <p class="text-center text-muted mb-5 fs-5">Crafting bespoke digital experiences through deep analysis and premium design systems.</p>
      
      <form id="ai-website-form">
        <div class="row g-4">
          <div class="col-md-6">
            <label for="businessName" class="form-label">Business Name</label>
            <input type="text" class="form-control" id="businessName" placeholder="e.g. Skyline Plumbing" required>
          </div>
          <div class="col-md-6">
            <label for="businessType" class="form-label">Industry Sector</label>
            <select class="form-select" id="businessType" required>
              <option value="" selected disabled>Select Type</option>
              <option value="plumber">Plumbing & HVAC</option>
              <option value="electrician">Electrical Services</option>
              <option value="restaurant">Fine Dining & Cafe</option>
              <option value="law">Legal & Advocacy</option>
              <option value="consulting">Business Consulting</option>
              <option value="fitness">Fitness & Wellness</option>
              <option value="realestate">Real Estate & Property</option>
              <option value="portfolio">Personal Portfolio</option>
              <option value="agency">Agency / Creative Studio</option>
              <option value="other">Other Professional Service</option>
            </select>
          </div>
          <div class="col-12">
            <label for="services" class="form-label">Bespoke Services & Value Proposition</label>
            <textarea class="form-control" id="services" rows="4" placeholder="List your key services and what makes you unique..." required></textarea>
          </div>
          <div class="col-md-6">
            <label for="location" class="form-label">Target Location / Market</label>
            <input type="text" class="form-control" id="location" placeholder="e.g. Mayfair, London" required>
          </div>
          <div class="col-md-6">
            <label for="style" class="form-label">Design Identity</label>
            <select class="form-select" id="style">
              <option value="modern" selected>Modern (Futuristic & Bold)</option>
              <option value="professional">Professional (Corporate & Trust)</option>
              <option value="creative">Creative (Asymmetric & Vibrant)</option>
              <option value="minimalist">Minimalist (Pure & Simple)</option>
            </select>
          </div>
        </div>
        
        <button type="submit" class="btn-generate">Generate Bespoke Preview</button>
      </form>
    </div>
  </div>

  <div class="loading-overlay" id="loadingOverlay">
    <div class="spinner mb-5"></div>
    <h3 id="loadingText">Architecting Your Site...</h3>
    <p class="text-muted fs-5" id="loadingSubtext">Our AI is drafting production-ready code.</p>
    <div class="progress-bar-container">
      <div class="progress-bar-inner"></div>
    </div>
  </div>

  <footer class="footer py-4 border-top">
    <div class="container">
      <p class="mb-0 text-center">©2025 FreeWebsiteTemplates. All Rights Reserved</p>
    </div>
  </footer>

  <script src="src/assets/libs/jquery/dist/jquery.min.js"></script>
  <script src="src/assets/libs/bootstrap/dist/js/bootstrap.bundle.min.js"></script>
  <script src="src/assets/libs/aos-master/dist/aos.js"></script>
  <script>
    AOS.init();
    
    const loadingMessages = [
      { main: "Initializing AI Architect...", sub: "Securing dedicated GPU cycles for your bespoke design." },
      { main: "Analyzing Market Logic...", sub: "Deep-diving into your localized competitive landscape." },
      { main: "Drafting Narrative Copy...", sub: "Crafting conversion-optimized headlines for your brand." },
      { main: "Calculating Design Tokens...", sub: "Synthesizing glassmorphism, depth, and fluid grids." },
      { main: "Generating Custom Code...", sub: "Compiling semantic HTML5 and cutting-edge CSS3." },
      { main: "Polishing Micro-Interactions...", sub: "Implementing smooth transitions and scroll-entry masks." },
      { main: "Finalizing Build...", sub: "Encrypting and preparing your master preview for launch." }
    ];
    
    // Pre-select category from URL if present
    document.addEventListener('DOMContentLoaded', () => {
      const urlParams = new URLSearchParams(window.location.search);
      const type = urlParams.get('type');
      if (type) {
        const select = document.getElementById('businessType');
        // Map common slugs to our options
        const mapping = {
          'business': 'consulting',
          'agency': 'consulting',
          'portfolio': 'other',
          'e-commerce': 'other',
          'services': 'consulting',
          'plumber': 'plumber',
          'electrician': 'electrician',
          'restaurant': 'restaurant',
          'law': 'law'
        };
        if (mapping[type]) select.value = mapping[type];
      }
    });

    document.getElementById('ai-website-form').addEventListener('submit', async function(e) {
      e.preventDefault();
      
      const formData = {
        businessName: document.getElementById('businessName').value,
        businessType: document.getElementById('businessType').value,
        services: document.getElementById('services').value,
        location: document.getElementById('location').value,
        style: document.getElementById('style').value
      };
      
      const overlay = document.getElementById('loadingOverlay');
      const mainText = document.getElementById('loadingText');
      const subText = document.getElementById('loadingSubtext');
      const progressBar = document.querySelector('.progress-bar-inner');
      
      overlay.style.display = 'flex';
      const API_BASE = (window.location.protocol === 'file:') ? 'http://127.0.0.1:5000' : '';
      
      try {
        const response = await fetch(`${API_BASE}/api/generate-site`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
        
        const initialData = await response.json();
        
        if (initialData.success) {
          // SYNC REDIRECT (Vercel Fix)
          if (initialData.previewUrl) {
            progressBar.style.width = '100%';
            mainText.innerText = "Website Created!";
            subText.innerText = "Taking you to your professional preview...";
            setTimeout(() => {
              window.location.href = initialData.previewUrl;
            }, 1000);
            return;
          }

          // ASYNC POLLING (Local/Standard Server)
          const slug = initialData.slug;
          let progress = 10;
          progressBar.style.width = '10%';

          // Polling loop
          const pollInterval = setInterval(async () => {
            try {
              const statusRes = await fetch(`${API_BASE}/api/status/${slug}?v=${Date.now()}`);
              const statusData = await statusRes.json();

              if (statusData.status === "COMPLETED") {
                clearInterval(pollInterval);
                progressBar.style.width = '100%';
                mainText.innerText = "Website Ready!";
                subText.innerText = "Redirecting to your preview...";
                setTimeout(() => {
                  window.location.href = statusData.previewUrl;
                }, 1000);
              } else if (statusData.status === "FAILED") {
                clearInterval(pollInterval);
                alert('Generation Failed: ' + statusData.message);
                overlay.style.display = 'none';
              } else {
                // Update text from server if available
                if (statusData.message) mainText.innerText = statusData.message;
                
                // Slow fake progress during AI processing
                if (progress < 95) {
                  progress += Math.random() * 2;
                  progressBar.style.width = progress + '%';
                }
              }
            } catch (err) {
              console.error("Polling error:", err);
            }
          }, 3000);
        } else {
          alert('Error: ' + initialData.message);
          overlay.style.display = 'none';
        }
      } catch (error) {
        console.error('Error:', error);
        alert('An error occurred. Please check your internet connection and try again.');
        overlay.style.display = 'none';
      }
    });
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
    return render_template_string(BUILD_WITH_AI_HTML)

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
                PROGRESS_STORE[site_slug] = {"status": "FAILED", "message": "Failed to generate website (v3)."}
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
