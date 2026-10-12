"""Drug name cleanup, so the same drug matches across recalls, shortages and the NDC directory."""
import re

# Words about the form, packaging or strength of a drug, not which drug it is.
FORM_WORDS = {
    "injection", "injections", "injectable", "solution", "solutions", "suspension", "emulsion",
    "tablet", "tablets", "capsule", "capsules", "caplet", "caplets", "oral", "orally", "for",
    "usp", "nf", "extended", "release", "delayed", "sustained", "controlled", "immediate",
    "er", "xr", "xl", "sr", "dr", "cr", "ir", "la", "odt", "disintegrating", "chewable",
    "film", "coated", "cream", "ointment", "gel", "lotion", "topical", "ophthalmic", "otic",
    "nasal", "spray", "inhalation", "inhaler", "aerosol", "powder", "lyophilized",
    "reconstitution", "vial", "vials", "ampule", "ampules", "ampoule", "ampoules", "syringe",
    "syringes", "prefilled", "pre", "filled", "kit", "single", "dose", "multi", "multiple",
    "use", "sterile", "concentrate", "intravenous", "iv", "im", "intramuscular",
    "subcutaneous", "infusion", "premix", "premixed", "bag", "bags", "bottle", "bottles",
    "pharmacy", "bulk", "package", "preservative", "free", "rx", "only", "drops", "liquid",
    "elixir", "syrup", "patch", "transdermal", "suppository", "suppositories", "vaginal",
    "rectal", "granules", "packet", "packets", "unit", "units", "mg", "mcg", "ml", "gm",
    "meq", "compounded", "the", "of", "an",
}
SYNONYMS = {"hcl": "hydrochloride", "hbr": "hydrobromide"}


def drug_key(name):
    """A drug name with the form, strength and packaging words removed.

    "Clindamycin Phosphate Injection, USP" and "CLINDAMYCIN PHOSPHATE" both become
    "clindamycin phosphate". Combination drugs get their parts sorted and joined with
    " + ", so the order they're written in doesn't matter.
    """
    if not name:
        return None
    text = re.sub(r"\([^)]*\)", " ", name.lower())
    parts = re.split(r"\s+and\s+|\s+in\s+|\s+with\s+|[;,/+&]", text)
    cleaned = set()
    for part in parts:
        words = []
        for word in re.sub(r"[^a-z0-9 ]", " ", part).split():
            word = SYNONYMS.get(word, word)
            if word in FORM_WORDS or len(word) < 2 or any(ch.isdigit() for ch in word):
                continue
            words.append(word)
        if words:
            cleaned.add(" ".join(words))
    return " + ".join(sorted(cleaned)) or None


def text_drug_name(description):
    """The drug name at the start of a recall's product description.

    "Heparin Sodium Injection, USP, 1,000 USP Units/mL" gives "Heparin Sodium Injection".
    It stops at the first comma, bracket, digit or "NDC".
    """
    if not description:
        return None
    head = re.split(r",|\(|\d|\bNDC\b", description, maxsplit=1)[0]
    return head.strip() or None
