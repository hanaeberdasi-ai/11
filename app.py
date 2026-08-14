"""
Shopify Product CSV Refiner — Streamlit App
============================================
Upload a Shopify products CSV → get a cleaned, optimised CSV back.

Features:
  • Removes products and variants without valid images
  • Fixes image URLs to prevent Shopify "Media processing failed" errors
  • Updates vendor name across all products
  • Converts HTML descriptions to clean plain text
  • Auto-generates SEO Title and Meta Description
  • Sets a uniform product category
  • Custom stock quantity
  • Adjustable price discount with compare-at price
  • Downloads the refined CSV ready for Shopify import
"""

import streamlit as st
import pandas as pd
import io
from utils.csv_processor import process_csv


# ──────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Shopify CSV Refiner",
    page_icon="🛍️",
    layout="wide",
)

# ──────────────────────────────────────────────
# CUSTOM STYLING
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.4rem;
        font-weight: 700;
        background: linear-gradient(90deg, #6C63FF, #E91E63);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #888;
        margin-bottom: 2rem;
    }
    .stat-card {
        background: #1E1E2E;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        border: 1px solid #333;
    }
    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #6C63FF;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #aaa;
        margin-top: 0.3rem;
    }
    .success-box {
        background: #0d3320;
        border: 1px solid #1db954;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        margin: 1rem 0;
    }
    .warning-box {
        background: #3a2a00;
        border: 1px solid #f0a500;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        margin: 1rem 0;
    }
    .info-box {
        background: #0d2033;
        border: 1px solid #2196F3;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        margin: 1rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────
st.markdown('<div class="main-header">🛍️ Shopify CSV Refiner</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Upload your Shopify products CSV → get a cleaned, '
    "SEO-optimised CSV ready for import.</div>",
    unsafe_allow_html=True,
)

st.divider()

# ──────────────────────────────────────────────
# STEP 1 — FILE UPLOAD
# ──────────────────────────────────────────────
st.markdown("### 📁 Step 1 — Upload your Shopify Products CSV")

uploaded_file = st.file_uploader(
    "Choose a CSV file exported from Shopify",
    type=["csv"],
    help="Go to Shopify Admin → Products → Export → CSV for Excel / Numbers",
)

if uploaded_file is not None:
    # Read the CSV
    try:
        raw_df = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    except Exception as e:
        st.error(f"❌ Could not read the CSV file: {e}")
        st.stop()

    st.success(f"✅ Loaded **{len(raw_df):,}** rows and **{len(raw_df.columns)}** columns.")

    with st.expander("👀 Preview raw data (first 10 rows)", expanded=False):
        st.dataframe(raw_df.head(10), use_container_width=True)

    st.divider()

    # ──────────────────────────────────────────
    # STEP 2 — CONFIGURATION
    # ──────────────────────────────────────────
    st.markdown("### ⚙️ Step 2 — Configure your refinements")

    col1, col2 = st.columns(2)

    with col1:
        vendor_name = st.text_input(
            "🏪 Vendor / Store name",
            value="",
            placeholder="e.g. terrificbuyss",
            help="This name will replace the vendor field on every product row.",
        )

    with col2:
        product_category = st.text_input(
            "📂 Product Category",
            value="",
            placeholder="e.g. Health & Beauty > Personal Care",
            help="This category will be set on every product's Type and Product Category columns.",
        )

    st.markdown("")

    col3, col4 = st.columns(2)

    with col3:
        stock_quantity = st.number_input(
            "📦 Stock Quantity",
            min_value=0,
            max_value=999999,
            value=50,
            step=1,
            help="Set this inventory quantity on every product variant.",
        )

    with col4:
        discount_percent = st.slider(
            "💰 Price Discount (%)",
            min_value=0,
            max_value=90,
            value=0,
            step=5,
            help=(
                "Reduce all variant prices by this percentage. "
                "The original price is saved as the 'Compare At Price' so customers see the discount."
            ),
        )

    # Show price preview
    if discount_percent > 0:
        example_price = 100.00
        new_price = round(example_price * (100 - discount_percent) / 100, 2)
        st.markdown(
            f'<div class="info-box">'
            f"💡 <strong>Price preview:</strong> A ${example_price:.2f} product becomes "
            f"<strong>${new_price:.2f}</strong> (−{discount_percent}%). "
            f"The original ${example_price:.2f} is stored as the Compare At Price."
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")

    # Summary of what will happen
    st.markdown("#### 🔧 The tool will automatically:")
    checks = [
        "Remove all products (and their variants) that have **no valid image**",
        "**Fix image URLs** — strip size suffixes, query params, convert .webp (prevents Shopify media errors)",
        "**Clean descriptions** — convert HTML to readable plain text",
        "**Generate SEO Title** and **Meta Description** for every product",
        f"Set **Stock Quantity** to `{stock_quantity}` on all variants",
    ]
    if discount_percent > 0:
        checks.append(f"Apply **{discount_percent}% price discount** (original saved as Compare At Price)")
    if vendor_name.strip():
        checks.append(f'Set **Vendor** to `{vendor_name.strip()}` on all products')
    if product_category.strip():
        checks.append(f'Set **Product Category** to `{product_category.strip()}`')

    for check in checks:
        st.markdown(f"- {check}")

    st.divider()

    # ──────────────────────────────────────────
    # STEP 3 — PROCESS
    # ──────────────────────────────────────────
    st.markdown("### 🚀 Step 3 — Process & Download")

    if st.button("🔄 Process CSV", type="primary", use_container_width=True):

        if not vendor_name.strip():
            st.warning("⚠️ You haven't entered a vendor name. The existing vendor values will be kept.")

        with st.spinner("Processing… this may take a moment for large files."):
            processed_df, stats = process_csv(
                raw_df.copy(),
                vendor=vendor_name.strip(),
                category=product_category.strip(),
                stock_quantity=int(stock_quantity),
                discount_percent=int(discount_percent),
            )

        # ──────────────────────────────────────
        # STATS DISPLAY
        # ──────────────────────────────────────
        st.markdown("")
        st.markdown("#### 📊 Processing Results")

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["original_rows"]:,}</div>'
                f'<div class="stat-label">Original Rows</div></div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["rows_removed_no_image"]:,}</div>'
                f'<div class="stat-label">Rows Removed<br>(No Image)</div></div>',
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["final_products"]:,}</div>'
                f'<div class="stat-label">Final Products</div></div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["images_cleaned"]:,}</div>'
                f'<div class="stat-label">Image URLs<br>Fixed</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")

        c5, c6, c7, c8 = st.columns(4)

        with c5:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["descriptions_cleaned"]:,}</div>'
                f'<div class="stat-label">Descriptions<br>Cleaned</div></div>',
                unsafe_allow_html=True,
            )
        with c6:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["seo_generated"]:,}</div>'
                f'<div class="stat-label">SEO Tags<br>Generated</div></div>',
                unsafe_allow_html=True,
            )
        with c7:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["prices_discounted"]:,}</div>'
                f'<div class="stat-label">Prices<br>Discounted</div></div>',
                unsafe_allow_html=True,
            )
        with c8:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-number">{stats["stock_updated"]:,}</div>'
                f'<div class="stat-label">Stock Rows<br>Updated</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")

        # Summary boxes
        if stats["rows_removed_no_image"] > 0:
            st.markdown(
                f'<div class="warning-box">⚠️ <strong>{stats["rows_removed_no_image"]}</strong> '
                f"rows were removed because their products had no valid images.</div>",
                unsafe_allow_html=True,
            )

        if stats["images_cleaned"] > 0:
            st.markdown(
                f'<div class="info-box">🖼️ <strong>{stats["images_cleaned"]}</strong> '
                f"image URLs were fixed (removed size suffixes, query params, etc.) "
                f"to prevent Shopify \"Media processing failed\" errors.</div>",
                unsafe_allow_html=True,
            )

        summary_items = [
            "• Products without images removed",
            "• Image URLs cleaned and fixed for Shopify compatibility",
            "• HTML descriptions converted to plain text",
            "• SEO Title & Meta Description generated",
            f"• Stock quantity set to <strong>{stock_quantity}</strong>",
        ]
        if discount_percent > 0:
            summary_items.append(
                f"• Prices reduced by <strong>{discount_percent}%</strong> (originals saved as Compare At Price)"
            )
        if vendor_name.strip():
            summary_items.append(f"• Vendor set to <strong>{vendor_name.strip()}</strong>")
        if product_category.strip():
            summary_items.append(f"• Category set to <strong>{product_category.strip()}</strong>")

        st.markdown(
            '<div class="success-box">✅ All refinements applied successfully:<br>'
            + "<br>".join(summary_items)
            + "</div>",
            unsafe_allow_html=True,
        )

        # Preview
        with st.expander("👀 Preview refined data (first 15 rows)", expanded=True):
            key_cols = []
            for c in [
                "Handle", "Title", "Body (HTML)", "Vendor", "Type",
                "Product Category", "SEO Title", "SEO Description",
                "Variant Price", "Variant Compare At Price",
                "Variant Inventory Qty",
                "Image Src", "Variant Image",
            ]:
                col_map = {col.strip().lower(): col for col in processed_df.columns}
                actual = col_map.get(c.strip().lower())
                if actual and actual in processed_df.columns:
                    key_cols.append(actual)

            if key_cols:
                st.dataframe(
                    processed_df[key_cols].head(15),
                    use_container_width=True,
                )
            else:
                st.dataframe(processed_df.head(15), use_container_width=True)

        # ──────────────────────────────────────
        # DOWNLOAD
        # ──────────────────────────────────────
        st.markdown("")
        st.markdown("#### 📥 Download Refined CSV")

        csv_buffer = io.StringIO()
        processed_df.to_csv(csv_buffer, index=False)
        csv_bytes = csv_buffer.getvalue().encode("utf-8")

        st.download_button(
            label="⬇️  Download Refined CSV",
            data=csv_bytes,
            file_name="shopify_products_refined.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )

        st.caption(
            "Import this file into Shopify via **Settings → Import** or the "
            "[Matrixify](https://apps.shopify.com/matrixify) app."
        )

else:
    # No file uploaded yet — show instructions
    st.info(
        "👆 Upload a Shopify products CSV to get started.\n\n"
        "**How to export from Shopify:**\n"
        "1. Go to **Shopify Admin → Products**\n"
        "2. Click **Export**\n"
        "3. Choose **All products** → **CSV for Excel / Numbers**\n"
        "4. Upload the downloaded file here"
    )

    st.divider()
    st.markdown("#### ✨ What this tool does")
    st.markdown(
        """
        | Feature | Description |
        |---------|-------------|
        | 🖼️ **Image Validation** | Removes products with no valid images |
        | 🔧 **Image URL Fixing** | Strips size suffixes & query params that cause Shopify errors |
        | 🏪 **Vendor Update** | Sets a uniform vendor/store name |
        | 📝 **Description Cleanup** | Strips HTML tags → clean plain text |
        | 🔍 **SEO Generation** | Auto-creates SEO Title & Meta Description |
        | 📂 **Category Assignment** | Sets your chosen category on every product |
        | 📦 **Stock Quantity** | Sets inventory count on all variants |
        | 💰 **Price Discount** | Reduces prices by a percentage with Compare At Price |
        | 📥 **CSV Export** | Downloads the refined file ready for Shopify import |
        """
    )
