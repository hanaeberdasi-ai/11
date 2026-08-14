"""
Auto-generate SEO Title and Meta Description for every product.
"""

import re


def generate_seo_title(
    title: str,
    vendor: str,
    category: str = "",
    max_length: int = 70,
) -> str:
    """Build a concise, keyword-rich SEO title."""
    title = str(title or "").strip()
    vendor = str(vendor or "").strip()
    category = str(category or "").strip()

    if not title:
        return ""

    category_short = ""
    if category:
        parts = [p.strip() for p in category.split(">")]
        category_short = parts[-1] if parts else ""

    if category_short and vendor:
        seo = f"{title} | {category_short} – {vendor}"
    elif vendor:
        seo = f"{title} – {vendor}"
    elif category_short:
        seo = f"{title} | {category_short}"
    else:
        seo = title

    if len(seo) > max_length:
        fallback = f"{title} – {vendor}" if vendor else title
        if len(fallback) > max_length:
            return fallback[: max_length - 1].rstrip() + "…"
        return fallback

    return seo


def generate_meta_description(
    title: str,
    plain_description: str,
    vendor: str,
    max_length: int = 160,
) -> str:
    """Build a compelling meta description from the plain-text description."""
    title = str(title or "").strip()
    vendor = str(vendor or "").strip()
    desc = str(plain_description or "").strip()

    if not desc and not title:
        return ""

    if not desc:
        base = f"Shop {title}"
        if vendor:
            base += f" at {vendor}"
        base += ". Fast shipping & great deals!"
        return base[:max_length]

    desc = re.sub(r"\s+", " ", desc).strip()

    cta = f" Shop now at {vendor}!" if vendor else ""
    budget = max_length - len(cta)

    if budget < 40:
        budget = max_length
        cta = ""

    snippet = desc[:budget]
    if len(desc) > budget:
        last_space = snippet.rfind(" ")
        if last_space > 20:
            snippet = snippet[:last_space]
        snippet = snippet.rstrip(".,;:!?") + "…"

    meta = snippet + cta
    return meta[:max_length]
