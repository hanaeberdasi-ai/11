"""
Utilities for validating and cleaning image URLs,
and removing products/variants that have no valid images.

Handles Shopify CDN URL normalization to prevent
"Media processing failed" errors on import.
"""

import re
import pandas as pd


def clean_image_url(url: str) -> str:
    """
    Validate, normalise, and fix a single image URL so that
    Shopify can actually download and process the image on import.

    Fixes applied:
      - Protocol-relative → https
      - Strip query strings and fragments (cache-busters break Shopify)
      - Remove Shopify CDN size suffixes like _800x, _grande, _large
      - Convert .webp → .jpg (Shopify re-encodes anyway)
      - Ensure the URL ends with a recognizable image extension
      - Reject data URIs, base64, and placeholder images

    Returns the cleaned URL or an empty string if invalid.
    """
    if not url or not str(url).strip():
        return ""

    url = str(url).strip()

    # ── Remove invisible / control characters ──
    url = re.sub(r"[\u0000-\u001F\u007F]", "", url)
    url = re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", url)
    url = url.replace("&amp;", "&")
    url = url.strip("\"'")

    if not url:
        return ""

    # ── Reject data URIs and base64 immediately ──
    if url.lower().startswith("data:"):
        return ""

    # ── Protocol-relative ──
    if url.startswith("//"):
        url = "https:" + url

    # ── Missing protocol for known CDN ──
    if re.match(r"^cdn\.shopify\.com/", url, re.I):
        url = "https://" + url

    # ── Extract first valid URL if embedded in junk ──
    match = re.search(r"https?://[^\s<>\"']+", url, re.I)
    if match:
        url = match.group(0)
    else:
        return ""

    # ── Force HTTPS ──
    url = re.sub(r"^http://", "https://", url, flags=re.I)

    # ── Must start with https:// ──
    if not url.lower().startswith("https://"):
        return ""

    # ── Basic host validation ──
    host_match = re.match(r"^https://([^/?#]+)", url, re.I)
    if not host_match:
        return ""

    host = re.sub(r":\d+$", "", host_match.group(1))
    if "." not in host or re.search(r"[^a-z0-9.\-]", host, re.I):
        return ""

    # ──────────────────────────────────────────────────────────
    # STRIP QUERY STRINGS AND FRAGMENTS
    # Shopify CDN URLs often have ?v=1234567890 or &width=800
    # These cache-buster params cause "Media processing failed"
    # because Shopify's importer can't follow the redirect chain.
    # ──────────────────────────────────────────────────────────
    url = url.split("?")[0].split("#")[0]

    # ──────────────────────────────────────────────────────────
    # REMOVE SHOPIFY CDN SIZE SUFFIXES
    # Examples:
    #   _800x.jpg      →  .jpg
    #   _800x800.png   →  .png
    #   _grande.jpg    →  .jpg
    #   _large.png     →  .png
    #   _compact.jpg   →  .jpg
    #   _1024x1024.jpg →  .jpg
    #   _2048x.webp    →  .webp
    #
    # These suffixed URLs often 404 or return redirect chains
    # that Shopify's media processor cannot handle.
    # ──────────────────────────────────────────────────────────
    size_suffixes = (
        r"_(pico|icon|thumb|small|compact|medium|large|grande|"
        r"1024x1024|2048x2048|master|\d+x\d*|\d*x\d+)"
    )
    url = re.sub(
        size_suffixes + r"(\.(jpe?g|png|gif|webp|bmp|tiff?))",
        r"\2",
        url,
        flags=re.I,
    )

    # ──────────────────────────────────────────────────────────
    # CONVERT .webp → .jpg
    # Shopify's importer sometimes fails to process .webp files
    # from external URLs.  The Shopify CDN usually serves the
    # same image at the .jpg extension.
    # ──────────────────────────────────────────────────────────
    if url.lower().endswith(".webp"):
        # Only convert for Shopify CDN URLs (safe to swap extension)
        if "cdn.shopify.com" in url.lower():
            url = re.sub(r"\.webp$", ".jpg", url, flags=re.I)

    # ──────────────────────────────────────────────────────────
    # ENSURE URL HAS A VALID IMAGE EXTENSION
    # Shopify rejects URLs without a recognizable image file
    # extension at the end of the path.
    # ──────────────────────────────────────────────────────────
    valid_extensions = re.compile(
        r"\.(jpe?g|png|gif|webp|bmp|tiff?|svg|heic|heif)$", re.I
    )
    if not valid_extensions.search(url):
        # Some CDN URLs use path-based transforms without an extension
        # e.g. .../image/upload/v123/product.  Skip these.
        return ""

    # ──────────────────────────────────────────────────────────
    # REJECT PLACEHOLDER / BROKEN IMAGES
    # ──────────────────────────────────────────────────────────
    placeholder_patterns = [
        r"no[\-_]?image",
        r"placeholder",
        r"default[\-_]?image",
        r"coming[\-_]?soon",
        r"image[\-_]?not[\-_]?available",
        r"photo[\-_]?coming",
        r"no[\-_]?photo",
    ]
    url_lower = url.lower()
    for pattern in placeholder_patterns:
        if re.search(pattern, url_lower):
            return ""

    # ── Encode spaces ──
    url = url.replace(" ", "%20")

    # ── Fix broken percent encoding ──
    url = re.sub(r"%(?![0-9a-fA-F]{2})", "%25", url)

    # ── Reject URLs with residual bad characters ──
    if re.search(r'[\s<>"\']', url):
        return ""

    return url


def remove_products_without_images(df: pd.DataFrame) -> tuple:
    """
    Remove entire products (all rows sharing a Handle) when
    **none** of their rows have a valid image in either
    'Image Src' or 'Variant Image'.

    Also drops individual image-only rows (Title is empty)
    whose image URL is invalid.

    Returns (filtered_df, removed_count).
    """
    if df.empty:
        return df, 0

    df = df.copy()

    # Normalise column names for lookup (case-insensitive)
    col_map = {c.strip().lower(): c for c in df.columns}

    image_src_col = col_map.get("image src")
    variant_image_col = col_map.get("variant image")
    handle_col = col_map.get("handle")
    title_col = col_map.get("title")

    if not handle_col:
        return df, 0

    # Build a set of handles that have at least one valid image
    handles_with_images = set()

    for _, row in df.iterrows():
        has_image = False

        if image_src_col:
            if clean_image_url(str(row.get(image_src_col, ""))):
                has_image = True

        if not has_image and variant_image_col:
            if clean_image_url(str(row.get(variant_image_col, ""))):
                has_image = True

        if has_image:
            handles_with_images.add(str(row[handle_col]).strip().lower())

    # Keep only rows whose handle is in the valid set
    mask = df[handle_col].apply(
        lambda h: str(h).strip().lower() in handles_with_images
    )

    filtered = df[mask].copy()

    # Additionally drop image-only rows (no title) with bad image URLs
    if title_col and image_src_col:
        def _keep_row(row):
            title = str(row.get(title_col, "")).strip()
            if title:
                return True  # product row — always keep
            # image-only row — keep only if image is valid
            return bool(clean_image_url(str(row.get(image_src_col, ""))))

        filtered = filtered[filtered.apply(_keep_row, axis=1)].copy()

    removed_count = len(df) - len(filtered)
    return filtered, removed_count
