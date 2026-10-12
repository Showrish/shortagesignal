"""
Day 4: give recalls, shortages and NDC directory products the same kind of IDs, so Day 5
can match them.

  recall_ids     one row per recall and NDC found, plus the recall's firm key.
                 A recall with no NDC still gets one row, so its firm key is there.
  shortage_ids   the same for every shortage listing ever seen in the snapshots
  ndc_directory  one row per package in FDA's NDC directory, with product code and firm key

NDCs come out as ndc11 (package, 5-4-2) and ndc9 (product, 5-4). See ndc.py.
"""
import json

from shortagesignal.firms import firm_key
from shortagesignal.ndc import extract_ndcs, normalize_ndc, normalize_product_ndc
from shortagesignal.storage import load_batch, write_parquet

ID_COLUMNS = ["firm_key", "ndc11", "ndc9", "source"]


def json_list(text, key):
    """Pull a list out of a JSON text field like openfda. Empty list if it isn't there."""
    if not text:
        return []
    try:
        value = json.loads(text).get(key, [])
    except (ValueError, AttributeError):
        return []
    return value if isinstance(value, list) else [value]


def directory_rows(products):
    """NDC directory products → one row per package, plus a lookup for dash-less codes.

    The lookup maps the 10 digits of each package code (dashes removed) to its 11-digit
    form. Digits that fit more than one package are left out, since they're ambiguous.
    """
    rows, lookup, ambiguous = [], {}, set()
    for product_ndc, labeler, generic, dosage_form, packaging in products:
        ndc9 = normalize_product_ndc(product_ndc)
        key = firm_key(labeler)
        codes = [p.get("package_ndc") for p in _json_items(packaging)]
        ndc11s = []
        for code in codes:
            ndc11 = normalize_ndc(code)
            if not ndc11:
                continue
            ndc11s.append(ndc11)
            digits = code.replace("-", "")
            if len(digits) == 10:
                if digits in lookup and lookup[digits] != ndc11:
                    ambiguous.add(digits)
                lookup[digits] = ndc11
        for ndc11 in ndc11s or [None]:
            rows.append({"ndc11": ndc11, "ndc9": ndc9, "firm_key": key, "labeler_name": labeler,
                         "generic_name": generic, "dosage_form": dosage_form})
    for digits in ambiguous:
        del lookup[digits]
    return rows, lookup


def _json_items(text):
    if not text:
        return []
    try:
        items = json.loads(text)
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def ids_for(firm, text, openfda_text, lookup):
    """Every NDC we can find for one recall or shortage listing, and where it came from."""
    key = firm_key(firm)
    packages, products = [], []   # (code, source)
    found = extract_ndcs(text)
    packages += [(code, "text") for code in found["package"]]
    products += [(code, "text_product") for code in found["product"]]
    packages += [(lookup[d], "directory_lookup") for d in found["digits10"] if d in lookup]
    packages += [(normalize_ndc(c), "openfda") for c in json_list(openfda_text, "package_ndc")]
    products += [(normalize_product_ndc(c), "openfda_product")
                 for c in json_list(openfda_text, "product_ndc")]

    rows, seen_packages, seen_products = [], set(), set()
    for ndc11, source in packages:
        if ndc11 and ndc11 not in seen_packages:
            seen_packages.add(ndc11)
            seen_products.add(ndc11[:10])
            rows.append({"firm_key": key, "ndc11": ndc11, "ndc9": ndc11[:10], "source": source})
    for ndc9, source in products:
        # Skip product codes we already have through one of their packages.
        if ndc9 and ndc9 not in seen_products:
            seen_products.add(ndc9)
            rows.append({"firm_key": key, "ndc11": None, "ndc9": ndc9, "source": source})
    return rows or [{"firm_key": key, "ndc11": None, "ndc9": None, "source": "none"}]


def build_ids(con, ndc_path, recalls_path, snapshots_path, out, workdir):
    """Build the three ID tables. out maps table name to output path. Returns coverage stats."""
    products = con.execute(f"""
        SELECT product_ndc, labeler_name, generic_name, dosage_form, packaging
        FROM read_parquet('{ndc_path.as_posix()}')
    """).fetchall()
    directory, lookup = directory_rows(products)
    columns = ["ndc11", "ndc9", "firm_key", "labeler_name", "generic_name", "dosage_form"]
    load_batch(con, directory, columns, "ndc_directory", workdir)
    write_parquet(con, "SELECT * FROM ndc_directory ORDER BY ndc9, ndc11", out["ndc_directory"])

    stats = {"directory_packages": len(directory)}
    sources = [
        ("recall", "recall_number", recalls_path,
         "SELECT recall_number, recalling_firm, product_description, openfda FROM read_parquet('{p}')"),
        # Every listing ever seen, so shortages that dropped off FDA's list keep their IDs.
        ("shortage", "shortage_key", snapshots_path,
         "SELECT shortage_key, arg_max(company_name, snapshot_date), "
         "concat_ws(' ', arg_max(package_ndc, snapshot_date), arg_max(presentation, snapshot_date)), "
         "NULL FROM read_parquet('{p}') GROUP BY shortage_key"),
    ]
    for kind, id_col, path, query in sources:
        rows = []
        for row_id, firm, text, openfda_text in con.execute(query.format(p=path.as_posix())).fetchall():
            for r in ids_for(firm, text, openfda_text, lookup):
                rows.append({id_col: row_id, **r})
        name = f"{kind}_ids"
        load_batch(con, rows, [id_col] + ID_COLUMNS, name, workdir)
        write_parquet(con, f"SELECT * FROM {name} ORDER BY {id_col}", out[name])
        total = len({r[id_col] for r in rows})
        with_ndc = len({r[id_col] for r in rows if r["ndc9"]})
        stats[f"{kind}s"] = total
        stats[f"{kind}s_with_ndc"] = with_ndc
        stats[f"{kind}s_with_ndc_pct"] = round(100 * with_ndc / total, 1) if total else 0.0
    return stats
