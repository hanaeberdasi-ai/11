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
  10. Return the refined DataFrame ready for download.
"""

import pandas as pd
from .html_cleaner import strip_html
from .image_validator import remove_products_without_images, clean_image_url
from .seo_generator import generate_seo_title, generate_meta_description


def _col(df: pd.DataFrame, name: str):
    """Return the actual column name (case-insensitive) or None."""
    mapping = {c.strip().lower(): c for c in df.columns}
    return mapping.get(name.strip().lower())


def _parse_price(value) -> float:
    """Parse a price string into a float. Returns -1 if invalid."""
    if isinstance(value, (int, float)):
        return float(value) if value == value else -1.0  # NaN check

    text = str(value or "").strip()
    text = text.replace(" ", "").replace("$", "").replace("€", "").replace("£", "")

    if not text:
        return -1.0

    # Handle comma as decimal separator (e.g. "19,99" with no dot)
    if "," in text and "." not in text and len(text.split(",")[-1]) <= 2:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        val = float(text)
        return val if val == val else -1.0  # NaN check
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

    handle_col = _col(df, "Handle")
    title_col = _col(df, "Title")
    body_col = _col(df, "Body (HTML)")
    vendor_col = _col(df, "Vendor")
    type_col = _col(df, "Type")
    image_src_col = _col(df, "Image Src")
    variant_image_col = _col(df, "Variant Image")
    seo_title_col = _col(df, "SEO Title")
    seo_desc_col = _col(df, "SEO Description")
    tags_col = _col(df, "Tags")

    # Price columns
    variant_price_col = _col(df, "Variant Price")
    compare_price_col = _col(df, "Variant Compare At Price")

    # Inventory columns
    inventory_qty_col = _col(df, "Variant Inventory Qty")

    # Category columns
    product_cat_col = _col(df, "Product Category")
    google_cat_col = _col(df, "Google Shopping / Google Product Category")

    if handle_col:
        stats["original_products"] = df[handle_col].nunique()

    # ------------------------------------------------------------------
    # STEP 1: Remove products without any valid image
    # ------------------------------------------------------------------
    df, removed = remove_products_without_images(df)
    stats["rows_removed_no_image"] = removed

    # ------------------------------------------------------------------
    # STEP 2: Clean ALL image URLs (fix size suffixes, query params, etc.)
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
    if vendor_col and vendor:
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
        if not seo_title_col:
            seo_title_col = "SEO Title"
            df[seo_title_col] = ""
        if not seo_desc_col:
            seo_desc_col = "SEO Description"
            df[seo_desc_col] = ""

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

        if type_col:
            df.loc[product_mask, type_col] = category

        if not product_cat_col:
            product_cat_col = "Product Category"
            df[product_cat_col] = ""
        df.loc[product_mask, product_cat_col] = category

        if google_cat_col:
            df.loc[product_mask, google_cat_col] = category

    # ------------------------------------------------------------------
    # STEP 7: Set stock quantity
    # ------------------------------------------------------------------
    if inventory_qty_col:
        df[inventory_qty_col] = stock_quantity
        stats["stock_updated"] = len(df)
    else:
        # Create the column if it doesn't exist
        inventory_qty_col = "Variant Inventory Qty"
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

                # Store original price as compare-at price
                if compare_price_col:
                    df.at[idx, compare_price_col] = f"{original_price:.2f}"
                else:
                    if "Variant Compare At Price" not in df.columns:
                        df["Variant Compare At Price"] = ""
                        compare_price_col = "Variant Compare At Price"
                    df.at[idx, "Variant Compare At Price"] = f"{original_price:.2f}"

                df.at[idx, variant_price_col] = f"{new_price:.2f}"
                prices_discounted += 1

        stats["prices_discounted"] = prices_discounted

    # ------------------------------------------------------------------
    # Final stats
    # ------------------------------------------------------------------
    stats["final_rows"] = len(df)
    if handle_col:
        stats["final_products"] = df[handle_col].nunique()

    return df, stats
