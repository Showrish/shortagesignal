"""
NDC (National Drug Code) helpers.

An NDC has three parts: labeler (the company), product, and package. FDA writes 10-digit
NDCs in three layouts (4-4-2, 5-3-2, 5-4-1). Billing systems use a single 11-digit layout
(5-4-2), made by adding a leading zero to the short part. Converting everything to 5-4-2
is what lets two datasets match.

  ndc11  package level, like 00409-4888-10
  ndc9   product level (labeler + product), like 00409-4888. Same drug, any package size
"""
import re

# Valid package NDC layouts: 4-4-2, 5-3-2, 5-4-1, plus the 11-digit 5-4-2 form.
NDC_PATTERN = r"\b(\d{4}-\d{4}-\d{2}|\d{5}-\d{3}-\d{2}|\d{5}-\d{4}-\d{1,2})\b"

PACKAGE_RE = re.compile(NDC_PATTERN)
# Two-part product codes and dash-less codes look like lot numbers, so they only count
# right after the word "NDC".
_AFTER_NDC = r"\bNDC(?:s|\s*No\.?|\s*Number)?[^0-9A-Za-z]{0,6}"
PRODUCT_RE = re.compile(_AFTER_NDC + r"(\d{4}-\d{4}|\d{5}-\d{3,4})(?![-\d])", re.IGNORECASE)
DIGITS_RE = re.compile(_AFTER_NDC + r"(\d{10,11})(?!\d)", re.IGNORECASE)


def normalize_ndc(code):
    """A package NDC in 11-digit 5-4-2 form, like 00409-4888-10. None if it isn't one."""
    if not code:
        return None
    code = code.strip()
    parts = code.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        labeler, product, package = parts
        layout = (len(labeler), len(product), len(package))
        if layout == (4, 4, 2):
            labeler = "0" + labeler
        elif layout == (5, 3, 2):
            product = "0" + product
        elif layout == (5, 4, 1):
            package = "0" + package
        elif layout != (5, 4, 2):
            return None
        return f"{labeler}-{product}-{package}"
    if code.isdigit() and len(code) == 11:
        return f"{code[:5]}-{code[5:9]}-{code[9:]}"
    return None


def normalize_product_ndc(code):
    """A product NDC (labeler + product) in 5-4 form, like 00409-4888. None if it isn't one."""
    if not code:
        return None
    parts = code.strip().split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    labeler, product = parts
    layout = (len(labeler), len(product))
    if layout == (4, 4):
        labeler = "0" + labeler
    elif layout == (5, 3):
        product = "0" + product
    elif layout != (5, 4):
        return None
    return f"{labeler}-{product}"


def extract_ndcs(text):
    """Find NDCs in free text.

    Returns normalized package codes, normalized product codes, and dash-less 10-digit
    codes. The last kind can't be normalized on its own, because the same 10 digits fit
    three layouts, so the NDC directory decides which one it is.
    """
    found = {"package": [], "product": [], "digits10": []}
    if not text:
        return found

    def add(kind, value):
        if value and value not in found[kind]:
            found[kind].append(value)

    for match in PACKAGE_RE.finditer(text):
        add("package", normalize_ndc(match.group(1)))
    for match in PRODUCT_RE.finditer(text):
        add("product", normalize_product_ndc(match.group(1)))
    for match in DIGITS_RE.finditer(text):
        digits = match.group(1)
        if len(digits) == 11:
            add("package", normalize_ndc(digits))
        else:
            add("digits10", digits)
    return found
