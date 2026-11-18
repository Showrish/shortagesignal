"""Company name cleanup, so the same firm matches across datasets."""
import re

# Words that differ between datasets but don't tell you which company it is.
DROP_WORDS = {
    "INC", "INCORPORATED", "LLC", "LTD", "LIMITED", "CO", "CORP", "CORPORATION", "COMPANY",
    "PLC", "LP", "LLP", "GMBH", "AG", "SA", "SPA", "PVT", "PRIVATE", "THE", "DIV", "DIVISION",
    "PHARMACEUTICAL", "PHARMACEUTICALS", "PHARMA", "LABORATORIES", "LABORATORY", "LABS",
    "USA", "US",
}


# A parent company named after the firm itself, like "Hospira, Inc., a Pfizer Company" or
# "Merck Sharp & Dohme Corp., a subsidiary of Merck & Co., Inc.". Kept, the parent's name would
# make one firm look like two, so it's dropped before cleaning.
AFFILIATION = re.compile(
    r",?\s+(?:an?\s+(?:wholly[\s-]owned\s+)?(?:subsidiary|division|affiliate|unit)\s+of\b"
    r"|an?\s+[\w&.'\- ]+?\s+company\b).*$",
    re.IGNORECASE)


def firm_key(name):
    """Uppercase, no punctuation, no legal or filler words, no repeats, and no parent company.

    "Pfizer Inc." and "PFIZER INC" both become "PFIZER", and "Hospira, Inc., a Pfizer Company"
    becomes "HOSPIRA", the same as plain "Hospira, Inc.".
    """
    if not name:
        return None
    text = AFFILIATION.sub("", name).upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    tokens = []
    for token in text.split():
        if len(token) > 1 and token not in DROP_WORDS and token not in tokens:
            tokens.append(token)
    return " ".join(tokens) or None
