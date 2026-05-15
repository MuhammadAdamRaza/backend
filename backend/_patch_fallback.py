"""One-shot patch for fallback template designs 0/1/2."""
from pathlib import Path

p = Path(__file__).parent / "app.py"
text = p.read_text(encoding="utf-8")

# --- _build_pricing_html vi==1 ---
old_pricing = """    if vi == 1:
        rows = []
        for tier, price, desc, feats, star in tiers:
            lis = "".join(f"<li>{_e(f)}</li>" for f in feats)
            fc = " price-row featured" if star else " price-row"
            rows.append(
                f'<motion-div class="{fc.strip()}"><div><span class="fw-bold text-uppercase small">{_e(tier)}</span>'
                f'<h3 class="hero-serif mb-0">{_e(price)}</h3></div><p class="muted mb-2">{_e(desc)}</p>'
                f'<ul class="small muted mb-3">{lis}</ul>'
                f'<a href="#contact" class="btn-main btn-main-soft">Select plan</a></div>'
            )
        return f'<div class="pricing-stack">{"".join(rows)}</motion-div>'"""

# fix - exact from file without motion-div typos
old_pricing = """    if vi == 1:
        rows = []
        for tier, price, desc, feats, star in tiers:
            lis = "".join(f"<li>{_e(f)}</li>" for f in feats)
            fc = " price-row featured" if star else " price-row"
            rows.append(
                f'<div class="{fc.strip()}"><motion-div><span class="fw-bold text-uppercase small">{_e(tier)}</span>'
                f'<h3 class="hero-serif mb-0">{_e(price)}</h3></div><p class="muted mb-2">{_e(desc)}</p>'
                f'<ul class="small muted mb-3">{lis}</ul>'
                f'<a href="#contact" class="btn-main btn-main-soft">Select plan</a></div>'
            )
        return f'<div class="pricing-stack">{"".join(rows)}</div>'"""

new_pricing = """    if vi == 1:
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
        return f'<div class="pricing-divi">{"".join(cards)}</div>'"""

# Read exact block from file
import re
m = re.search(
    r"    if vi == 1:\n        rows = \[\].*?return f'<div class=\"pricing-stack\">.*?</motion-div>'",
    text,
    re.DOTALL,
)
if not m:
    m = re.search(
        r"    if vi == 1:\n        rows = \[\].*?return f'<div class=\"pricing-stack\">.*?</motion-div>'",
        text,
        re.DOTALL,
    )
if m:
    text = text[: m.start()] + new_pricing + text[m.end() :]
    print("pricing patched")
else:
    # line-based fallback
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == "if vi == 1:" and i > 900 and "rows = []" in lines[i + 1]:
            lines[i : i + 12] = [l + "\n" for l in new_pricing.split("\n") if l or True]
            # fix last line newline
            block = [x if x.endswith("\n") else x + "\n" for x in new_pricing.split("\n")]
            lines[i : i + 12] = block
            text = "".join(lines)
            print("pricing patched (line-based)")
            break

text = text.replace(
    'return f\'<section class="sec sec-editorial pt-0"><div class="container container-narrow"><motion-div class="stats-inline">{inner}</div></div></section>\'.replace("motion-div", "motion-div")',
    'return f\'<section class="sec sec-divi-band pt-0"><div class="container container-narrow"><div class="stats-inline">{inner}</div></div></section>\'.replace("div", "motion-div")',
)
text = text.replace(
    "sec sec-editorial pt-0",
    "sec sec-divi-band pt-0",
    1,
)

text = text.replace(
    'return f\'<div class="team-row">{"".join(parts)}</div>\'.replace("div", "div")',
    'return f\'<div class="team-row-divi">{"".join(parts)}</div>\'.replace("motion-div", "motion-div")',
)

text = text.replace(
    'f\'<div class="col-md-6"><div class="box h-100">\'\n                f\'<div class="text-warning mb-2">★★★★★</div><p class="mb-3">"{q}"</p>\'',
    'f\'<div class="col-md-6"><div class="box box-divi h-100">\'\n                f\'<div class="text-warning mb-2">★★★★★</div><p class="mb-3">"{q}"</p>\'',
)

text = text.replace(
    'f\'<div class="col-md-6 col-lg-3"><div class="box h-100">\'',
    'f\'<div class="col-md-6 col-lg-3"><div class="box box-landia h-100">\'',
    1,
)

old_hero_1 = """    if vi == 1:
        hero_body = f\"\"\"<div class="row justify-content-center text-center"><div class="col-lg-10">
<div class="hero-editorial-photo mb-4">{hero_editorial_el}</div>
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> Serving {loc}</span>
<h1 class="{h1c}">{headline}</h1>
<p class="{lc}">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4 justify-content-center">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">Services</a></div>
<p class="small muted">Trusted in {loc} · Clear quotes · 5★ rated</p>
</div></div>\"\"\""""

new_hero_1 = """    if vi == 1:
        _hl = headline if isinstance(headline, str) else str(headline)
        if " in " in _hl:
            _hp, _hs = _hl.split(" in ", 1)
            _h1_html = f'{_e(_hp)} <span class="accent">in {_e(_hs)}</span>'
        else:
            _h1_html = headline
        hero_body = f\"\"\"<div class="row justify-content-center text-center"><div class="col-lg-10">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> Serving {loc}</span>
<h1 class="{h1c}">{_h1_html}</h1>
<p class="{lc}">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-5 justify-content-center">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">View services</a></motion-div>
<p class="small muted mb-5">Trusted in {loc} · Clear quotes · 5★ rated</p>
<div class="motion-frame mx-auto" style="max-width:900px">{hero_editorial_el}</div>
</div></div>\"\"\""""

if old_hero_1 in text:
    text = text.replace(old_hero_1, new_hero_1)
    print("divi hero patched")
else:
    print("WARN: divi hero block not found")

old_hero_0 = """    else:
        hero_body = f\"\"\"<div class="row align-items-center g-5">
<div class="col-lg-7">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> {loc}</span>
<h1 class="{h1c}">{headline}</h1>
<p class="{lc}" style="max-width:38rem">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">Services</a></div>
<p class="small muted">Trusted locally · Insured · 5★ reviews</p>
</div>
<div class="col-lg-5 d-none d-lg-block">{hero_img_el}</div></div>\"\"\""""

new_hero_0 = """    else:
        hero_body = f\"\"\"<div class="hero-preview"><div class="row align-items-center g-5">
<div class="col-lg-7">
<span class="badge-top d-inline-block mb-3"><i class="bi bi-geo-alt me-1"></i> Serving {loc}</span>
<h1 class="{h1c}">{headline}</h1>
<p class="{lc}" style="max-width:38rem">{pitch}</p>
<div class="d-flex flex-wrap gap-3 mb-4">
<a href="#contact" class="{cta}">Book consultation</a>
<a href="#services" class="btn-ghost btn-lg">Services</a></div>
<p class="small muted">Trusted locally · Insured · 5★ reviews</p>
</div>
<div class="col-lg-5 d-none d-lg-block"><div class="motion-frame">{hero_img_el}</div></div></div></div>\"\"\""""

if old_hero_0 in text:
    text = text.replace(old_hero_0, new_hero_0)
    print("landia hero patched")

text = text.replace(
    'nav_extra = "rounded-pill px-4" if vi == 1 else ""',
    'nav_extra = "rounded-pill px-4" if vi in (0, 1) else ""',
)

# team section - no row wrapper for vi==1
text = text.replace(
    '"team": f"""<section class="sec" id="team"><div class="container"><h2 class="display-5 fw-bold text-center mb-2">Meet the team</h2>\n<p class="text-center muted mb-5">The people behind {name}</p><div class="row g-4">{team_html}</div></div></section>""".replace("div", "div")',
    '"team": f"""<section class="{sec_cls}" id="team"><div class="container"><h2 class="{h2c} text-center mb-2">Meet the team</h2>\n<p class="text-center muted mb-5">The people behind {name}</p>{"<div class=\\"row g-4\\">" + team_html + "</div>" if vi != 1 else team_html}</div></section>""".replace("motion-div", "motion-div")',
)

# blog cards
text = text.replace(
    'f\'<div class="col-md-4"><div class="box h-100">\'',
    'f\'<div class="col-md-4"><div class="{box_cls} h-100">\'',
    1,
)

# how block non-brutal - replace class="box with box_cls in how_steps
text = text.replace(
    """        how_block = \"\"\"<div class="row g-4 how-steps-h">
<div class="col-md-4"><div class="box text-center h-100">""",
    """        how_block = f\"\"\"<div class="row g-4 how-steps-h">
<div class="col-md-4"><div class="{box_cls} text-center h-100">""",
    1,
)
text = text.replace(
    """<motion-div class="col-md-4"><div class="box text-center h-100">""",
    """<div class="col-md-4"><motion-div class="{box_cls} text-center h-100">""",
)
# fix botched replace - read and fix manually in second pass

p.write_text(text, encoding="utf-8")
print("done")
