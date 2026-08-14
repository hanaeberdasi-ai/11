"""
Utilities for stripping HTML from Shopify product descriptions
and converting them to clean plain text.
"""

import re
import html
from bs4 import BeautifulSoup


def decode_html_entities(text: str) -> str:
    """Decode all HTML entities (named, decimal, hex) in a string."""
    if not text:
        return ""

    result = html.unescape(text)

    result = re.sub(
        r"&#(\d+);",
        lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else " ",
        result,
    )
    result = re.sub(
        r"&#x([0-9a-fA-F]+);",
        lambda m: (
            chr(int(m.group(1), 16))
            if int(m.group(1), 16) < 0x110000
            else " "
        ),
        result,
    )
    return result


def strip_html(raw_html: str) -> str:
    """
    Convert an HTML product description to clean, readable plain text.

    Preserves paragraph breaks and list formatting.
    Removes all tags, scripts, styles, and invisible characters.
    """
    if not raw_html or not str(raw_html).strip():
        return ""

    text = str(raw_html)

    # Remove zero-width and BOM characters
    text = re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", text)

    # Decode entities before parsing (handles double-encoded content)
    for _ in range(3):
        text = decode_html_entities(text)

    # Use BeautifulSoup for robust tag removal
    soup = BeautifulSoup(text, "lxml")

    # Remove script, style, noscript entirely
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Insert structural whitespace before extracting text
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag_name in ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]:
        for tag in soup.find_all(tag_name):
            tag.insert_before("\n")
            tag.insert_after("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for tag_name in ["ul", "ol"]:
        for tag in soup.find_all(tag_name):
            tag.insert_after("\n")

    plain = soup.get_text()

    # Final cleanup
    plain = decode_html_entities(plain)
    plain = re.sub(r"\r", "\n", plain)
    plain = re.sub(r"[ \t]+", " ", plain)
    plain = re.sub(r" *\n *", "\n", plain)
    plain = re.sub(r"\n{3,}", "\n\n", plain)

    return plain.strip()
