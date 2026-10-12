"""Company name cleanup, so the same firm matches across datasets."""
import re

# Words that differ between datasets but don't tell you which company it is.
DROP_WORDS = {
    "INC", "INCORPORATED", "LLC", "LTD", "LIMITED", "CO", "CORP", "CORPORATION", "COMPANY",
    "PLC", "LP", "LLP", "GMBH", "AG", "SA", "SPA", "PVT", "PRIVATE", "THE", "DIV", "DIVISION",
    "PHARMACEUTICAL", "PHARMACEUTICALS", "PHARMA", "LABORATORIES", "LABORATORY", "LABS",
    "USA", "US",
}


def firm_key(name):
    """Uppercase, no punctuation, no legal or filler words, no repeats.

    "Pfizer Inc." and "PFIZER INC" both become "PFIZER".
    """
    if not name:
        return None
    text = name.upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    tokens = []
    for token in text.split():
        if len(token) > 1 and token not in DROP_WORDS and token not in tokens:
            tokens.append(token)
    return " ".join(tokens) or None
