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
    "meq", "compounded", "the", "of", "an", "flavor", "flavors", "flavored", "flavour", "lozenge",
    "lozenges",
}
# Not "base" or "cough" on their own: the NDC directory has bulk listings like "Fentanyl Base",
# and stripping the word would make them plain "fentanyl", which breaks links to the shortage
# list's "fentanyl citrate". The phrase "cough drop" is safe to drop.
PHRASES = re.compile(r"\bcough drops?\b")
SYNONYMS = {"hcl": "hydrochloride", "hbr": "hydrobromide"}

# Store brands and plain words that turn up where a drug name should be, like an NDC listing
# whose generic name is "CVS" or a recall whose text starts with the store's name. They never
# count as a drug.
NOT_DRUGS = frozenset({
    "cvs", "cvs health", "walgreens", "equate", "kroger", "rite aid", "up", "good neighbor",
    "leader", "careone", "care one", "topcare", "basic care", "amazon basic care",
    "signature care", "exchange select", "sunmark", "quality choice", "member mark",
    "members mark", "kirkland signature", "harris teeter", "publix", "meijer", "good sense",
    "goodsense", "health mart", "dg health",
    "eye", "ear", "ice", "oak", "spf", "tmj", "md",   # not "fat": "Fat Emulsion" cleans to it
})

# What a drug is mixed into, rather than a second drug, written the way drug_key writes them.
DILUENTS = frozenset({"sodium chloride", "dextrose", "water", "bacteriostatic water",
                      "lactated ringer", "ringer"})


def drug_key(name):
    """A drug name with the form, strength and packaging words removed.

    "Clindamycin Phosphate Injection, USP" and "CLINDAMYCIN PHOSPHATE" both become
    "clindamycin phosphate". Combination drugs get their parts sorted and joined with
    " + ", so the order they're written in doesn't matter.
    """
    if not name:
        return None
    text = PHRASES.sub(" ", re.sub(r"\([^)]*\)", " ", name.lower()))
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


def text_drug_name(description, past_strengths=False):
    """The drug name at the start of a recall's product description.

    "Heparin Sodium Injection, USP, 1,000 USP Units/mL" gives "Heparin Sodium Injection".
    It stops at the first comma, bracket, digit or "NDC". With past_strengths, it doesn't stop
    at digits, so "Ergotamine Tartrate 1 mg/Caffeine 100 mg Suppository" keeps the caffeine,
    and drug_key drops the strengths.
    """
    if not description:
        return None
    stops = r",|\(|\bNDC\b" if past_strengths else r",|\(|\d|\bNDC\b"
    head = re.split(stops, description, maxsplit=1)[0]
    return head.strip() or None
