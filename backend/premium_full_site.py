"""Full single-page site builder — imported into app.py."""
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
    features_html = "".join(feat_rows).replace("div", "div").replace("</div>", "</div>")

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
