"""NDC (National Drug Code) helpers. Normalization gets added in Batch 2."""

# Valid package NDC layouts: 4-4-2, 5-3-2, 5-4-1, plus the 11-digit 5-4-2 form.
NDC_PATTERN = r"\b(\d{4}-\d{4}-\d{2}|\d{5}-\d{3}-\d{2}|\d{5}-\d{4}-\d{1,2})\b"
