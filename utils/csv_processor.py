"""
Core processing pipeline:
  1. Load the uploaded Shopify CSV.
  2. Remove products without images.
  3. Replace vendor.
  4. Clean descriptions (HTML → plain text).
  5. Generate SEO title + meta description.
  6. Set the product category for all rows.
  7. Return the refined DataFrame ready for download.
"""

import pandas as pd
from .html_cleaner import strip_html
from .image_validator import remove_products_without_images, clean_image_url
from .seo_generator import generate_seo_title, generate_meta_description


def _col(df: pd.DataFrame, name: str):
    """Return the actual column name (case-insensitive) or None."""
    mapping = {c.strip().lower(): c for c in df.columns}
    return mapping.get(name.strip().lower())


def process_csv(
    df: pd.DataFrame,
    vendor: str,
    category: str,
) -> tuple[pd.DataFrame, dict]:
    """
    Run the full processing pipeline on the raw Shopify CSV.

    Parameters
    ----------
    df : pd.DataFrame – the raw CSV loaded into a DataFrame.
    vendor : str – the new vendor / store name.
    category : str – the product category to assign to every product.

    Returns
    -------
    (processed_df, stats) where stats is a dict of counters.
    """
    stats = {
        "original_rows": len(df),
        "original_products": 0,
        "rows_removed_no_image": 0,
        "final_rows": 0,
        "final_products": 0,
        "descriptions_cleaned": 0,
        "seo_generated": 0,
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
    published_col = _col(df, "Published")
    status_col = _col(df, "Status")
    tags_col = _col(df, "Tags")

    # Google / Shopify taxonomy columns (may or may not exist)
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
    # STEP 2: Clean all image URLs that remain
    # ------------------------------------------------------------------
    if image_src_col:
        df[image_src_col] = df[image_src_col].apply(
            lambda v: clean_image_url(str(v)) if pd.notna(v) else ""
        )
    if variant_image_col:
        df[variant_image_col] = df[variant_image_col].apply(
            lambda v: clean_image_url(str(v)) if pd.notna(v) else ""
        )

    # ------------------------------------------------------------------
    # STEP 3: Update vendor on every row
    # ------------------------------------------------------------------
    if vendor_col:
        # Only set vendor on product rows (rows that have a title)
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

        # Rename column to "Body (HTML)" stays — Shopify expects it
        # but content is now plain text which Shopify also accepts.

    # ------------------------------------------------------------------
    # STEP 5: Generate SEO Title + Meta Description for product rows
    # ------------------------------------------------------------------
    if title_col:
        # Ensure SEO columns exist
        if not seo_title_col:
            seo_title_col = "SEO Title"
            df[seo_title_col] = ""
        if not seo_desc_col:
            seo_desc_col = "SEO Description"
            df[seo_desc_col] = ""

        seo_count = 0
        for idx, row in df.iterrows():
            title_val = str(row.get(title_col, "")).strip()
            if not title_val:
                continue  # image-only row

            desc_val = ""
            if body_col:
                desc_val = str(row.get(body_col, "")).strip()

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

        # Create or update Product Category column
        if not product_cat_col:
            product_cat_col = "Product Category"
            df[product_cat_col] = ""
        df.loc[product_mask, product_cat_col] = category

        if google_cat_col:
            df.loc[product_mask, google_cat_col] = category

    # ------------------------------------------------------------------
    # Final stats
    # ------------------------------------------------------------------
    stats["final_rows"] = len(df)
    if handle_col:
        stats["final_products"] = df[handle_col].nunique()

    return df, stats
