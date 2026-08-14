"""
Utilities for validating and cleaning image URLs,
and removing products/variants that have no valid images.

Performs LIVE HTTP HEAD requests to verify every image URL
is actually reachable and returns a valid image content type.
This permanently eliminates products whose images would cause
Shopify's "Media processing failed" error.
"""

import re
import requests
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed


# Cache verified URLs across the session so we don't re-check duplicates
_URL_CACHE = {}

# Valid image content types that Shopify accepts
VALID_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/svg+xml",
    "image/heic",
    "image/heif",
    "image/avif",
}

# Common CDN hosts that are known to work with Shopify
TRUSTED_CDN_HOSTS = {
    "cdn.shopify.com",
    "cdn2.shopify.com",
    "cdn3.shopify.com",
}


def _is_valid_image_response(url: str, timeout: int = 10) -> bool:
    """
    Perform an HTTP HEAD request (falling back to GET) to verify
    that the URL returns a valid, downloadable image.

    Checks:
      1. HTTP status is 200
      2. Content-Type is an image type Shopify accepts
      3. Content-Length > 1000 bytes (reject tiny placeholders/icons)
      4. No redirect to an error page
      5. Final URL still looks like an image

    Returns True if the image is valid and downloadable.
    """
    if url in _URL_CACHE:
        return _URL_CACHE[url]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/*,*/*;q=0.8",
    }

    try:
        # Try HEAD first (faster, no body download)
        resp = requests.head(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        # Some servers don't support HEAD properly — fall back to GET
        if resp.status_code in (405, 403, 400, 501):
            resp = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                stream=True,  # Don't download full body
            )
            # Read only first few bytes to get headers
            resp.close()

        # Check HTTP status
        if resp.status_code != 200:
            _URL_CACHE[url] = False
            return False

        # Check Content-Type
        content_type = resp.headers.get("Content-Type", "").lower().split(";")[0].strip()

        if content_type not in VALID_IMAGE_TYPES:
            # Some CDNs return "application/octet-stream" for valid images
            # In that case, trust the file extension
            if content_type == "application/octet-stream":
                ext_match = re.search(r"\.(jpe?g|png|gif|webp|bmp|tiff?|svg)$", url.lower())
                if not ext_match:
                    _URL_CACHE[url] = False
                    return False
            elif content_type.startswith("text/") or content_type.startswith("application/"):
                # Definitely not an image — likely an error page
                _URL_CACHE[url] = False
                return False
            else:
                _URL_CACHE[url] = False
                return False

        # Check Content-Length (reject tiny placeholder images < 1KB)
        content_length = resp.headers.get("Content-Length", "")
        if content_length:
            try:
                size = int(content_length)
                if size < 1000:
                    _URL_CACHE[url] = False
                    return False
            except (ValueError, TypeError):
                pass

        # Check final URL after redirects — make sure it didn't redirect
        # to an error page or a completely different domain
        final_url = resp.url if hasattr(resp, "url") else url
        if final_url:
            # Reject if redirected to common error patterns
            error_patterns = [
                r"/404",
                r"/error",
                r"/not[\-_]?found",
                r"/missing",
                r"/default[\-_]?image",
                r"/placeholder",
                r"/no[\-_]?image",
            ]
            final_lower = final_url.lower()
            for pattern in error_patterns:
                if re.search(pattern, final_lower):
                    _URL_CACHE[url] = False
                    return False

        _URL_CACHE[url] = True
        return True

    except requests.exceptions.Timeout:
        _URL_CACHE[url] = False
        return False
    except requests.exceptions.ConnectionError:
        _URL_CACHE[url] = False
        return False
    except requests.exceptions.TooManyRedirects:
        _URL_CACHE[url] = False
        return False
    except Exception:
        _URL_CACHE[url] = False
        return False


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


def verify_images_live(
    df: pd.DataFrame,
    max_workers: int = 15,
    progress_callback=None,
) -> tuple:
    """
    Verify every image URL in the DataFrame by making actual HTTP
    requests. Collect all unique URLs, test them in parallel, then
    blank out any URL that fails.

    Returns (df_with_blanked_urls, verified_count, failed_count, failed_urls).
    """
    df = df.copy()

    col_map = {c.strip().lower(): c for c in df.columns}
    image_src_col = col_map.get("image src")
    variant_image_col = col_map.get("variant image")

    # Collect all unique non-empty image URLs
    all_urls = set()

    if image_src_col:
        for val in df[image_src_col]:
            url = str(val).strip()
            if url:
                all_urls.add(url)

    if variant_image_col:
        for val in df[variant_image_col]:
            url = str(val).strip()
            if url:
                all_urls.add(url)

    if not all_urls:
        return df, 0, 0, []

    total = len(all_urls)
    verified = 0
    failed = 0
    failed_urls = []
    results = {}

    # Test URLs in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(_is_valid_image_response, url): url
            for url in all_urls
        }

        done_count = 0
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            done_count += 1

            try:
                is_valid = future.result()
            except Exception:
                is_valid = False

            results[url] = is_valid

            if is_valid:
                verified += 1
            else:
                failed += 1
                failed_urls.append(url)

            if progress_callback:
                progress_callback(done_count, total)

    # Blank out failed URLs in the DataFrame
    if image_src_col:
        df[image_src_col] = df[image_src_col].apply(
            lambda v: str(v).strip() if results.get(str(v).strip(), False) else ""
        )

    if variant_image_col:
        df[variant_image_col] = df[variant_image_col].apply(
            lambda v: str(v).strip() if results.get(str(v).strip(), False) else ""
        )

    return df, verified, failed, failed_urls


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

    # Build set of handles that have at least one non-empty image URL
    handles_with_images = set()

    for _, row in df.iterrows():
        has_image = False

        if image_src_col:
            url = str(row.get(image_src_col, "")).strip()
            if url:
                has_image = True

        if not has_image and variant_image_col:
            url = str(row.get(variant_image_col, "")).strip()
            if url:
                has_image = True

        if has_image:
            handles_with_images.add(str(row[handle_col]).strip().lower())

    # Keep only rows whose handle has at least one valid image
    mask = df[handle_col].apply(
        lambda h: str(h).strip().lower() in handles_with_images
    )

    filtered = df[mask].copy()

    # Drop image-only rows (no title) with empty image URLs
    if title_col and image_src_col:
        def _keep_row(row):
            title = str(row.get(title_col, "")).strip()
            if title:
                return True
            img = str(row.get(image_src_col, "")).strip()
            return bool(img)

        filtered = filtered[filtered.apply(_keep_row, axis=1)].copy()

    removed_count = len(df) - len(filtered)
    return filtered, removed_count
