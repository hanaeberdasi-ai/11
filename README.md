# 🛍️ Shopify CSV Refiner

A Streamlit web app that cleans and optimises Shopify product CSV exports.

## Features

- **Image validation** — removes products/variants without valid images
- **Vendor update** — sets a uniform store name across all products
- **HTML → plain text** — converts messy HTML descriptions to readable text
- **SEO generation** — auto-creates SEO Title and Meta Description
- **Category assignment** — applies a single product category to all items
- **CSV download** — exports a clean file ready for Shopify import

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/shopify-csv-refiner.git
cd shopify-csv-refiner

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
