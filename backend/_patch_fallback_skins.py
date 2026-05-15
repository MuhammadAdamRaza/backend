# One-off patch for fallback preview skins — run from repo root: python backend/_patch_fallback_skins.py
from pathlib import Path

path = Path(__file__).resolve().parent / "app.py"
text = path.read_text(encoding="utf-8")

# --- _theme ---
old_theme = '''def _theme(vi, primary, secondary, surface):
    """Each variation tints from the user's form colours — not fixed navy/purple."""
    primary, secondary, surface = _hex_norm(primary), _hex_norm(secondary), _hex_norm(surface)
    if vi == 0:
        bg = _hex_mix(primary, "#000000", 0.78)
        card = _hex_mix(primary, "#ffffff", 0.14)
        text = "#f8fafc"
        muted = _hex_mix(secondary, "#94a3b8", 0.45)
        alt = _hex_mix(primary, secondary, 0.22)
    elif vi == 1:
        bg = surface
        card = _hex_mix(surface, "#ffffff", 0.9)
        text = "#0f172a" if _hex_lum(bg) > 0.58 else "#f1f5f9"
        muted = _hex_mix(primary, "#64748b", 0.55)
        alt = _hex_mix(surface, primary, 0.14)
    else:
        bg = _hex_mix(secondary, primary, 0.62)
        card = _hex_mix(secondary, "#ffffff", 0.18)
        text = "#f8fafc" if _hex_lum(bg) < 0.5 else "#0f172a"
        muted = _hex_mix(secondary, "#cbd5e1", 0.48)
        alt = _hex_mix(secondary, primary, 0.38)
    return {"bg": bg, "text": text, "card": card, "muted": muted, "alt": alt}'''

new_theme = '''def _theme(vi, primary, secondary, surface):
    """vi=0 Landia light · vi=1 Divi dark · vi=2 brutal — tinted from form colours."""
    primary, secondary, surface = _hex_norm(primary), _hex_norm(secondary), _hex_norm(surface)
    if vi == 0:
        bg = _hex_mix(surface, "#ffffff", 0.92)
        card = "#ffffff"
        text = "#1e293b"
        muted = _hex_mix(primary, "#64748b", 0.62)
        alt = _hex_mix(surface, primary, 0.08)
    elif vi == 1:
        bg = _hex_mix(primary, "#000000", 0.82)
        card = _hex_mix(primary, "#ffffff", 0.1)
        text = "#f8fafc"
        muted = _hex_mix(secondary, "#94a3b8", 0.48)
        alt = _hex_mix(primary, secondary, 0.2)
    else:
        bg = _hex_mix(secondary, primary, 0.62)
        card = _hex_mix(secondary, "#ffffff", 0.18)
        text = "#f8fafc" if _hex_lum(bg) < 0.5 else "#0f172a"
        muted = _hex_mix(secondary, "#cbd5e1", 0.48)
        alt = _hex_mix(secondary, primary, 0.38)
    return {"bg": bg, "text": text, "card": card, "muted": muted, "alt": alt}'''

if old_theme not in text:
    raise SystemExit("_theme block not found")
text = text.replace(old_theme, new_theme)

# --- _hero_overlay ---
old_overlay = '''def _hero_overlay(primary, secondary, bg, vi):
    """Tinted overlay — lighter on editorial so the photo stays visible."""
    if vi == 1:
        return (
            f"linear-gradient(180deg, {_hex_mix(primary, '#000000', 0.55)}99 0%, "
            f"{_hex_mix(bg, '#ffffff', 0.2)}bb 55%, {_hex_mix(bg, '#ffffff', 0.05)}ee 100%)"
        )
    if vi == 2:
        return (
            f"linear-gradient(90deg, {_hex_mix(primary, '#000000', 0.5)}cc 0%, "
            f"{_hex_mix(secondary, '#000000', 0.35)}88 40%, transparent 62%)"
        )
    return (
        f"linear-gradient(135deg, {_hex_mix(primary, '#000000', 0.65)}cc 0%, "
        f"{_hex_mix(secondary, '#000000', 0.5)}99 45%, {_hex_mix(bg, '#000000', 0.25)}88 100%)"
    )'''

new_overlay = '''def _hero_overlay(primary, secondary, bg, vi):
    """Landia: soft wash · Divi: cinematic dark · Brutal: side gradient."""
    if vi == 0:
        return (
            f"linear-gradient(180deg, {_hex_mix(bg, '#ffffff', 0.15)}ee 0%, "
            f"{_hex_mix(primary, '#ffffff', 0.08)}44 100%)"
        )
    if vi == 1:
        return (
            f"linear-gradient(180deg, {_hex_mix(primary, '#000000', 0.55)}99 0%, "
            f"{_hex_mix(bg, '#000000', 0.35)}bb 55%, {_hex_mix(bg, '#000000', 0.15)}ee 100%)"
        )
    if vi == 2:
        return (
            f"linear-gradient(90deg, {_hex_mix(primary, '#000000', 0.5)}cc 0%, "
            f"{_hex_mix(secondary, '#000000', 0.35)}88 40%, transparent 62%)"
        )
    return (
        f"linear-gradient(135deg, {_hex_mix(primary, '#000000', 0.65)}cc 0%, "
        f"{_hex_mix(secondary, '#000000', 0.5)}99 45%, {_hex_mix(bg, '#000000', 0.25)}88 100%)"
    )'''

text = text.replace(old_overlay, new_overlay)

# --- _skin ---
old_skin = '''def _skin(vi):
    """Per-design typography, spacing, and CSS class names."""
    if vi == 0:
        return {
            "layout": "template-dark",
            "fonts": "https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,600;0,9..40,700;1,9..40,400&display=swap",
            "font_h": "'DM Sans', system-ui, sans-serif",
            "font_b": "'DM Sans', system-ui, sans-serif",
            "nav": "nav-dark",
            "hero_cls": "hero-dark",
            "sec": "sec-pad-lg",
            "box": "box-round",
            "h2": "display-5 fw-bold",
            "h1": "display-3 fw-bold lh-sm",
            "lead": "lead fs-4 muted",
            "cta_btn": "btn-main btn-lg",
        }
    if vi == 1:
        return {
            "layout": "template-editorial",
            "fonts": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&family=Outfit:wght@300;400;500;600;700&display=swap",
            "font_h": "'Cormorant Garamond', Georgia, serif",
            "font_b": "'Outfit', system-ui, sans-serif",
            "nav": "nav-editorial",
            "hero_cls": "hero-editorial",
            "sec": "sec-editorial",
            "box": "box-flat",
            "h2": "hero-serif",
            "h1": "hero-serif display-2",
            "lead": "lead muted fs-5",
            "cta_btn": "btn-main btn-main-soft btn-lg",
        }
    return {
        "layout": "template-brutal",
        "fonts": "https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@400;500;600;700&display=swap",
        "font_h": "'Archivo Black', Impact, sans-serif",
        "font_b": "'Archivo', system-ui, sans-serif",
        "nav": "nav-brutal",
        "hero_cls": "hero-brutal",
        "sec": "sec-brutal",
        "box": "box-sharp",
        "h2": "display-5 fw-bold text-uppercase",
        "h1": "display-2 fw-bold text-uppercase lh-1",
        "lead": "fs-5 muted",
        "cta_btn": "btn-main btn-main-block btn-lg",
    }'''

new_skin = '''def _skin(vi):
    """vi=0 BootstrapMade Landia · vi=1 Divi gallery · vi=2 brutal."""
    if vi == 0:
        return {
            "layout": "template-landia",
            "fonts": "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap",
            "font_h": "'Nunito', system-ui, sans-serif",
            "font_b": "'Nunito', system-ui, sans-serif",
            "nav": "nav-landia",
            "hero_cls": "hero-landia",
            "sec": "sec-landia",
            "box": "box-landia",
            "h2": "display-5 fw-bold",
            "h1": "display-3 fw-bold lh-sm",
            "lead": "lead fs-5 muted",
            "cta_btn": "btn-main btn-lg rounded-pill px-4",
        }
    if vi == 1:
        return {
            "layout": "template-divi",
            "fonts": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
            "font_h": "'Inter', system-ui, sans-serif",
            "font_b": "'Inter', system-ui, sans-serif",
            "nav": "nav-divi",
            "hero_cls": "hero-divi",
            "sec": "sec-divi",
            "box": "box-divi",
            "h2": "h2-divi",
            "h1": "h1-divi",
            "lead": "lead-divi",
            "cta_btn": "btn-main btn-main-pill",
        }
    return {
        "layout": "template-brutal",
        "fonts": "https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@400;500;600;700&display=swap",
        "font_h": "'Archivo Black', Impact, sans-serif",
        "font_b": "'Archivo', system-ui, sans-serif",
        "nav": "nav-brutal",
        "hero_cls": "hero-brutal",
        "sec": "sec-brutal",
        "box": "box-sharp",
        "h2": "display-5 fw-bold text-uppercase",
        "h1": "display-2 fw-bold text-uppercase lh-1",
        "lead": "fs-5 muted",
        "cta_btn": "btn-main btn-main-block btn-lg",
    }'''

text = text.replace(old_skin, new_skin)

path.write_text(text, encoding="utf-8")
print("Patched _theme, _hero_overlay, _skin")
