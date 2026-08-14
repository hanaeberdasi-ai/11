"""
Utilities for validating and cleaning image URLs,
and removing products/variants that have no valid images.
"""

import re
import pandas as pd


def clean_image_url(url: str) -> str:
    """
    Validate and normalise a single image URL.

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

    # Force HTTPS
    url = re.sub(r"^http://", "https://", url, flags=re.I)

    # Encode spaces
    url = url.replace(" ", "%20")

    # Must start with https://
    if not url.lower().startswith("https://"):
        return ""

    # Basic host validation
    host_match = re.match(r"^https://([^/?#]+)", url, re.I)
    if not host_match:
        return ""

    host = re.sub(r":\d+$", "", host_match.group(1))
    if "." not in host or re.search(r"[^a-z0-9.\-]", host, re.I):
        return ""

    # Reject URLs with residual bad characters
    if re.search(r'[\s<>"\']', url):
        return ""

    return url


def remove_products_without_images(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove entire products (all rows sharing a Handle) when
    **none** of their rows have a valid image in either
    'Image Src' or 'Variant Image'.

    Also drops individual image-only rows (Title is empty)
    whose image URL is invalid.

    Returns a new DataFrame with only image-bearing products.
    """
    if df.empty:
        return df

    df = df.copy()

    # Normalise column names for lookup (case-insensitive)
    col_map = {c.strip().lower(): c for c in df.columns}

    image_src_col = col_map.get("image src")
    variant_image_col = col_map.get("variant image")
    handle_col = col_map.get("handle")
    title_col = col_map.get("title")

    if not handle_col:
        return df

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
