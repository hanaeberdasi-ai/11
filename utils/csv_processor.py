"""
Core processing pipeline:
  1. Load the uploaded Shopify CSV.
  2. Remove products without images.
  3. Clean remaining image URLs (strip size suffixes, query params, etc.)
  4. Replace vendor.
  5. Clean descriptions (HTML → plain text).
  6. Generate SEO title + meta description.
  7. Set the product category for all rows.
  8. Set stock quantity.
  9. Apply price discount.
  10. Ensure all required Shopify fields are populated.
  11. Return the refined DataFrame ready for download.
"""

import pandas as pd
from .html_cleaner import strip_html
from .image_validator import remove_products_without_images, clean_image_url
from .seo_generator import generate_seo_title, generate_meta_description


def _col(df: pd.DataFrame, name: str):
    """Return the actual column name (case-insensitive) or None."""
    mapping = {c.strip().lower(): c for c in df.columns}
    return mapping.get(name.strip().lower())


def _ensure_col(df: pd.DataFrame, name: str) -> str:
    """Ensure a column exists in the DataFrame. Returns the column name."""
    existing = _col(df, name)
    if existing:
        return existing
    df[name] = ""
    return name


def _parse_price(value) -> float:
    """Parse a price string into a float. Returns -1 if invalid."""
    if isinstance(value, (int, float)):
        return float(value) if value == value else -1.0

    text = str(value or "").strip()
    text = text.replace(" ", "").replace("$", "").replace("€", "").replace("£", "")

    if not text:
        return -1.0

    if "," in text and "." not in text and len(text.split(",")[-1]) <= 2:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        val = float(text)
        return val if val == val else -1.0
    except (ValueError, OverflowError):
        return -1.0


def process_csv(
    df: pd.DataFrame,
    vendor: str,
    category: str,
    stock_quantity: int = 50,
    discount_percent: int = 0,
) -> tuple:
    """
    Run the full processing pipeline on the raw Shopify CSV.

    Parameters
    ----------
    df : pd.DataFrame – the raw CSV loaded into a DataFrame.
    vendor : str – the new vendor / store name.
    category : str – the product category to assign to every product.
    stock_quantity : int – inventory quantity to set on every variant.
    discount_percent : int – percentage to reduce prices (0 = no change).

    Returns
    -------
    (processed_df, stats) where stats is a dict of counters.
    """
    stats = {
        "original_rows": len(df),
        "original_products": 0,
        "rows_removed_no_image": 0,
        "images_cleaned": 0,
        "final_rows": 0,
        "final_products": 0,
        "descriptions_cleaned": 0,
        "seo_generated": 0,
        "prices_discounted": 0,
        "stock_updated": 0,
    }

    # ------------------------------------------------------------------
    # Ensure ALL required Shopify columns exist before processing
    # ------------------------------------------------------------------
    handle_col = _ensure_col(df, "Handle")
    title_col = _ensure_col(df, "Title")
    body_col = _ensure_col(df, "Body (HTML)")
    vendor_col = _ensure_col(df, "Vendor")
    type_col = _ensure_col(df, "Type")
    tags_col = _ensure_col(df, "Tags")
    published_col = _ensure_col(df, "Published")
    image_src_col = _ensure_col(df, "Image Src")
    image_pos_col = _ensure_col(df, "Image Position")
    image_alt_col = _ensure_col(df, "Image Alt Text")
    variant_image_col = _ensure_col(df, "Variant Image")
    seo_title_col = _ensure_col(df, "SEO Title")
    seo_desc_col = _ensure_col(df, "SEO Description")
    variant_price_col = _ensure_col(df, "Variant Price")
    compare_price_col = _ensure_col(df, "Variant Compare At Price")
    inventory_qty_col = _ensure_col(df, "Variant Inventory Qty")
    product_cat_col = _ensure_col(df, "Product Category")
    google_cat_col = _ensure_col(df, "Google Shopping / Google Product Category")

    # Critical columns that cause Shopify import errors if missing/empty
    variant_sku_col = _ensure_col(df, "Variant SKU")
    variant_grams_col = _ensure_col(df, "Variant Grams")
    variant_inv_tracker_col = _ensure_col(df, "Variant Inventory Tracker")
    variant_inv_policy_col = _ensure_col(df, "Variant Inventory Policy")
    variant_fulfillment_col = _ensure_col(df, "Variant Fulfillment Service")
    variant_requires_shipping_col = _ensure_col(df, "Variant Requires Shipping")
    variant_taxable_col = _ensure_col(df, "Variant Taxable")
    variant_weight_unit_col = _ensure_col(df, "Variant Weight Unit")
    gift_card_col = _ensure_col(df, "Gift Card")
    status_col = _ensure_col(df, "Status")
    option1_name_col = _ensure_col(df, "Option1 Name")
    option1_value_col = _ensure_col(df, "Option1 Value")

    if handle_col:
        stats["original_products"] = df[handle_col].nunique()

    # ------------------------------------------------------------------
    # STEP 1: Remove products without any valid image
    # ------------------------------------------------------------------
    df, removed = remove_products_without_images(df)
    stats["rows_removed_no_image"] = removed

    # ------------------------------------------------------------------
    # STEP 2: Clean ALL image URLs
    # ------------------------------------------------------------------
    images_cleaned = 0

    if image_src_col:
        for idx in df.index:
            original = str(df.at[idx, image_src_col]) if pd.notna(df.at[idx, image_src_col]) else ""
            cleaned = clean_image_url(original)
            if original.strip() and cleaned != original.strip():
                images_cleaned += 1
            df.at[idx, image_src_col] = cleaned

    if variant_image_col:
        for idx in df.index:
            original = str(df.at[idx, variant_image_col]) if pd.notna(df.at[idx, variant_image_col]) else ""
            cleaned = clean_image_url(original)
            if original.strip() and cleaned != original.strip():
                images_cleaned += 1
            df.at[idx, variant_image_col] = cleaned

    stats["images_cleaned"] = images_cleaned

    # ------------------------------------------------------------------
    # STEP 3: Update vendor on product rows
    # ------------------------------------------------------------------
    if vendor:
        if title_col:
            mask = df[title_col].apply(lambda v: str(v).strip() != "")
            df.loc[mask, vendor_col] = vendor
        else:
            df[vendor_col] = vendor

    # ------------------------------------------------------------------
    # STEP 4: Clean descriptions — HTML → plain text
    # ------------------------------------------------------------------
    if body_col:
        def _clean_desc(val):
            raw = str(val) if pd.notna(val) else ""
            if not raw.strip():
                return ""
            return strip_html(raw)

        df[body_col] = df[body_col].apply(_clean_desc)
        stats["descriptions_cleaned"] = int(
            df[body_col].apply(lambda v: len(str(v).strip()) > 0).sum()
        )

    # ------------------------------------------------------------------
    # STEP 5: Generate SEO Title + Meta Description for product rows
    # ------------------------------------------------------------------
    if title_col:
        seo_count = 0
        for idx in df.index:
            title_val = str(df.at[idx, title_col]).strip()
            if not title_val:
                continue

            desc_val = ""
            if body_col:
                desc_val = str(df.at[idx, body_col]).strip()

            df.at[idx, seo_title_col] = generate_seo_title(
                title_val, vendor, category
            )
            df.at[idx, seo_desc_col] = generate_meta_description(
                title_val, desc_val, vendor
            )
            seo_count += 1

        stats["seo_generated"] = seo_count

    # ------------------------------------------------------------------
    # STEP 6: Set product category on product rows
    # ------------------------------------------------------------------
    if category:
        if title_col:
            product_mask = df[title_col].apply(
                lambda v: str(v).strip() != ""
            )
        else:
            product_mask = pd.Series(True, index=df.index)

        df.loc[product_mask, type_col] = category
        df.loc[product_mask, product_cat_col] = category

        if google_cat_col:
            df.loc[product_mask, google_cat_col] = category

    # ------------------------------------------------------------------
    # STEP 7: Set stock quantity
    # ------------------------------------------------------------------
    df[inventory_qty_col] = stock_quantity
    stats["stock_updated"] = len(df)

    # ------------------------------------------------------------------
    # STEP 8: Apply price discount
    # ------------------------------------------------------------------
    if discount_percent > 0 and variant_price_col:
        multiplier = (100 - discount_percent) / 100.0
        prices_discounted = 0

        for idx in df.index:
            original_price = _parse_price(df.at[idx, variant_price_col])
            if original_price > 0:
                new_price = round(original_price * multiplier, 2)
                df.at[idx, compare_price_col] = f"{original_price:.2f}"
                df.at[idx, variant_price_col] = f"{new_price:.2f}"
                prices_discounted += 1

        stats["prices_discounted"] = prices_discounted

    # ------------------------------------------------------------------
    # STEP 9: Fill ALL required Shopify fields to prevent import errors
    #
    # Shopify will reject the CSV if these are blank:
    #   - Variant Fulfillment Service  → must be "manual"
    #   - Variant Inventory Policy     → must be "deny" or "continue"
    #   - Variant Inventory Tracker    → "shopify" or blank
    #   - Variant Requires Shipping    → "TRUE" or "FALSE"
    #   - Variant Taxable              → "TRUE" or "FALSE"
    #   - Variant Grams                → numeric or 0
    #   - Variant Weight Unit          → "g", "kg", "lb", "oz"
    #   - Published                    → "TRUE" or "FALSE"
    #   - Status                       → "active", "draft", or "archived"
    #   - Gift Card                    → "TRUE" or "FALSE"
    #   - Option1 Name / Value         → at minimum "Title" / "Default Title"
    # ------------------------------------------------------------------

    for idx in df.index:
        is_product_row = str(df.at[idx, title_col]).strip() != ""

        # ── Variant Fulfillment Service (REQUIRED — cannot be blank) ──
        current_fulfillment = str(df.at[idx, variant_fulfillment_col]).strip().lower()
        if current_fulfillment not in ("manual", "shopify", "gift_card"):
            # Check if there's any third-party fulfillment service name
            if not current_fulfillment or current_fulfillment in ("", "nan", "none"):
                df.at[idx, variant_fulfillment_col] = "manual"

        # ── Variant Inventory Policy (REQUIRED — must be "deny" or "continue") ──
        current_policy = str(df.at[idx, variant_inv_policy_col]).strip().lower()
        if current_policy not in ("deny", "continue"):
            df.at[idx, variant_inv_policy_col] = "deny"

        # ── Variant Inventory Tracker ──
        current_tracker = str(df.at[idx, variant_inv_tracker_col]).strip().lower()
        if current_tracker not in ("shopify", "shipwire", "amazon_marketplace_web", ""):
            df.at[idx, variant_inv_tracker_col] = "shopify"
        if not current_tracker or current_tracker in ("nan", "none"):
            df.at[idx, variant_inv_tracker_col] = "shopify"

        # ── Variant Requires Shipping ──
        current_shipping = str(df.at[idx, variant_requires_shipping_col]).strip().upper()
        if current_shipping not in ("TRUE", "FALSE"):
            df.at[idx, variant_requires_shipping_col] = "TRUE"

        # ── Variant Taxable ──
        current_taxable = str(df.at[idx, variant_taxable_col]).strip().upper()
        if current_taxable not in ("TRUE", "FALSE"):
            df.at[idx, variant_taxable_col] = "TRUE"

        # ── Variant Grams ──
        current_grams = str(df.at[idx, variant_grams_col]).strip()
        try:
            grams_val = float(current_grams)
            if grams_val != grams_val:  # NaN
                df.at[idx, variant_grams_col] = "0"
        except (ValueError, TypeError):
            if not current_grams or current_grams.lower() in ("nan", "none", ""):
                df.at[idx, variant_grams_col] = "0"

        # ── Variant Weight Unit ──
        current_weight_unit = str(df.at[idx, variant_weight_unit_col]).strip().lower()
        if current_weight_unit not in ("g", "kg", "lb", "oz"):
            df.at[idx, variant_weight_unit_col] = "g"

        # ── Product-row-only fields ──
        if is_product_row:
            # Published
            current_published = str(df.at[idx, published_col]).strip().upper()
            if current_published not in ("TRUE", "FALSE"):
                df.at[idx, published_col] = "TRUE"

            # Status
            current_status = str(df.at[idx, status_col]).strip().lower()
            if current_status not in ("active", "draft", "archived"):
                df.at[idx, status_col] = "active"

            # Gift Card
            current_gift = str(df.at[idx, gift_card_col]).strip().upper()
            if current_gift not in ("TRUE", "FALSE"):
                df.at[idx, gift_card_col] = "FALSE"

            # Option1 Name — must have at least one option
            current_opt_name = str(df.at[idx, option1_name_col]).strip()
            if not current_opt_name or current_opt_name.lower() in ("nan", "none", ""):
                df.at[idx, option1_name_col] = "Title"

            # Option1 Value
            current_opt_value = str(df.at[idx, option1_value_col]).strip()
            if not current_opt_value or current_opt_value.lower() in ("nan", "none", ""):
                df.at[idx, option1_value_col] = "Default Title"

    # ------------------------------------------------------------------
    # Final stats
    # ------------------------------------------------------------------
    stats["final_rows"] = len(df)
    if handle_col:
        stats["final_products"] = df[handle_col].nunique()

    return df, stats
