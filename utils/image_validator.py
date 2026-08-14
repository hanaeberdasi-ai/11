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

    Returns the cleaned URL or an empty string if invalid.
    """
    if not url or not str(url).strip():
        return ""

    url = str(url).strip()

    # Remove invisible / control characters
    url = re.sub(r"[\u0000-\u001F\u007F]", "", url)
    url = re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", url)
    url = url.replace("&amp;", "&")
    url = url.strip("\"'")

    if not url:
        return ""

    # Reject data URIs and base64
    if url.lower().startswith("data:"):
        return ""

    # Protocol-relative
    if url.startswith("//"):
        url = "https:" + url

    # Missing protocol for known CDN
    if re.match(r"^cdn\.shopify\.com/", url, re.I):
        url = "https://" + url

    # Extract first valid URL if embedded in junk
    match = re.search(r"https?://[^\s<>\"']+", url, re.I)
    if match:
        url = match.group(0)
    else:
        return ""

    # Force HTTPS
    url = re.sub(r"^http://", "https://", url, flags=re.I)

    if not url.lower().startswith("https://"):
        return ""

    # Basic host validation
    host_match = re.match(r"^https://([^/?#]+)", url, re.I)
    if not host_match:
        return ""

    host = re.sub(r":\d+$", "", host_match.group(1))
    if "." not in host or re.search(r"[^a-z0-9.\-]", host, re.I):
        return ""

    # Strip query strings and fragments
    url = url.split("?")[0].split("#")[0]

    # Remove Shopify CDN size suffixes
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

    # Convert .webp → .jpg for Shopify CDN
    if url.lower().endswith(".webp"):
        if "cdn.shopify.com" in url.lower():
            url = re.sub(r"\.webp$", ".jpg", url, flags=re.I)

    # Ensure valid image extension
    valid_extensions = re.compile(
        r"\.(jpe?g|png|gif|webp|bmp|tiff?|svg|heic|heif)$", re.I
    )
    if not valid_extensions.search(url):
        return ""

    # Reject placeholder images
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

    # Encode spaces and fix broken percent encoding
    url = url.replace(" ", "%20")
    url = re.sub(r"%(?![0-9a-fA-F]{2})", "%25", url)

    if re.search(r'[\s<>"\']', url):
        return ""

    return url


def remove_products_without_images(df: pd.DataFrame) -> tuple:
    """
    Remove entire products (all rows sharing a Handle) when
    none of their rows have a valid image.

    Returns (filtered_df, removed_count).
    """
    if df.empty:
        return df, 0

    df = df.copy()

    col_map = {c.strip().lower(): c for c in df.columns}

    image_src_col = col_map.get("image src")
    variant_image_col = col_map.get("variant image")
    handle_col = col_map.get("handle")
    title_col = col_map.get("title")

    if not handle_col:
        return df, 0

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

    mask = df[handle_col].apply(
        lambda h: str(h).strip().lower() in handles_with_images
    )

    filtered = df[mask].copy()

    if title_col and image_src_col:
        def _keep_row(row):
            title = str(row.get(title_col, "")).strip()
            if title:
                return True
            return bool(clean_image_url(str(row.get(image_src_col, ""))))

        filtered = filtered[filtered.apply(_keep_row, axis=1)].copy()

    removed_count = len(df) - len(filtered)
    return filtered, removed_count
