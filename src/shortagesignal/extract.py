"""
Day 9: Claude names the drug for recalls the pipeline couldn't.

  python -m shortagesignal.extract eval    score Claude against the drugs in your hand audit

How it works:
  1. The queue is every recall that matching couldn't name a drug for. Most of them have
     no NDC either, so they're the unmatched recalls from Day 5.
  2. Claude Haiku reads each one's product description and answers through a tool: the
     active ingredients by generic name, the strength, the dosage form, whether it was
     compounded, and how sure it is. Each distinct description is asked once, and the
     answer is cached by its text and the prompt version.
  3. Matching uses Claude's drug only when Claude is fairly sure and the name is a drug we
     know exists (see check_claude_key in match.py). Everything else lands in
     extract_review.csv, with the reason it wasn't used.
  4. Matching then runs again with Claude's names, so those recalls can link to
     shortages by drug and firm. The run log keeps the before and after numbers.

The daily run only calls Claude when SHORTAGESIGNAL_USE_CLAUDE=1, like tagging.
"""
import csv
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from shortagesignal.audit import SHEET_PATH, read_sheet
from shortagesignal.config import NDC_PATH, RECALLS_PATH, ROOT, SNAPSHOTS_PATH
from shortagesignal.drugs import drug_key
from shortagesignal.match import check_claude_key, known_drugs
from shortagesignal.storage import load_batch, write_parquet
from shortagesignal.tagging import MODEL, PRICE_IN, PRICE_OUT, make_client

EVAL_CACHE = ROOT / "audit" / "claude_eval_drugs.csv"
EVAL_RESULTS = ROOT / "audit" / "extraction_results.md"
USE_CONFIDENCE = {"high", "medium"}   # low-confidence names go to review instead
FORMS = ["tablet", "capsule", "injection", "solution", "suspension", "cream or ointment",
         "powder", "inhalation", "patch", "drops", "other", "unknown"]
CACHE_COLUMNS = ["text_hash", "ingredients", "drug_key", "strength", "dosage_form",
                 "compounded", "confidence", "model", "prompt_version", "extracted_at"]
REVIEW_COLUMNS = ["recall_number", "recalling_firm", "product_description", "ingredients",
                  "confidence", "problem"]

SYSTEM_PROMPT = "\n".join([
    "You read the product description from an FDA drug recall and say which drug it is.",
    "",
    "Rules:",
    "1. List the active ingredients by generic name, the way a drug label writes them,",
    "   with the salt when there is one: 'morphine sulfate', 'hydromorphone hydrochloride'.",
    "2. Combination products: list every active ingredient.",
    "3. If only a brand name is given, give its generic name, but only when you're sure",
    "   which drug it is.",
    "4. Leave out inactive ingredients, preservatives, diluents and bases. Sodium chloride",
    "   in 'X in 0.9% sodium chloride' is a diluent. Sodium chloride on its own, as in",
    "   'Sodium Chloride Injection', is the drug.",
    "5. Expand an abbreviation only when you're sure of it (PGE-1 is alprostadil).",
    "6. If the product isn't a drug (a device, a dietary supplement, a cosmetic), or the",
    "   description doesn't say which drug it is, return no ingredients.",
    "7. compounded is true when a pharmacy or outsourcing facility made it to order",
    "   (compounded, 503B, outsourcing facility), false otherwise.",
    "8. confidence: high when the description names the drug plainly, medium when you had",
    "   to interpret it, low when you're guessing.",
])
DRUG_TOOL = {
    "name": "record_drug",
    "description": "Record which drug one recalled product is.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ingredients": {"type": "array", "items": {"type": "string"},
                            "description": "Active ingredients by generic name. Empty if unclear."},
            "strength": {"type": "string", "description": "Like '10 mg/mL'. Empty if not given."},
            "dosage_form": {"type": "string", "enum": FORMS},
            "compounded": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["ingredients", "strength", "dosage_form", "compounded", "confidence"],
    },
}
# Changes whenever the prompt, the tool or the model changes, so old answers get redone.
PROMPT_VERSION = hashlib.md5((MODEL + SYSTEM_PROMPT + json.dumps(DRUG_TOOL, sort_keys=True))
                             .encode()).hexdigest()[:8]


# ---------------------------------------------------------------- Claude

def text_hash(firm, description):
    return hashlib.md5(f"{firm or ''}\n{description or ''}".encode()).hexdigest()


def key_from(ingredients):
    """Claude's ingredient list as a drug key, the same way matching writes them."""
    names = [str(n) for n in ingredients or [] if str(n).strip()]
    return drug_key(" + ".join(names)) if names else None


def claude_extract(client, firm, description):
    """Ask Claude which drug one product is. None if the call fails."""
    try:
        message = client.messages.create(
            model=MODEL, max_tokens=300, system=SYSTEM_PROMPT,
            tools=[DRUG_TOOL], tool_choice={"type": "tool", "name": DRUG_TOOL["name"]},
            messages=[{"role": "user",
                       "content": f"Recalling firm: {firm}\nProduct description: {description}"}],
        )
    except Exception as exc:   # one bad call shouldn't stop the run
        print(f"    Claude call failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    for block in message.content:
        if getattr(block, "type", "") == "tool_use":
            answer = block.input
            ingredients = [str(n).strip().lower() for n in answer.get("ingredients") or []
                           if str(n).strip()]
            form = answer.get("dosage_form")
            confidence = answer.get("confidence")
            return {"ingredients": ingredients,
                    "drug_key": key_from(ingredients),
                    "strength": str(answer.get("strength") or "")[:100],
                    "dosage_form": form if form in FORMS else "unknown",
                    "compounded": "true" if answer.get("compounded") is True else "false",
                    "confidence": confidence if confidence in ("high", "medium", "low") else "low",
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens}
    return None


def extract_many(client, items, seconds=900, workers=4):
    """Ask about (text_hash, firm, description) items a few at a time, until time runs out."""
    results, deadline, chunk_size = [], time.monotonic() + seconds, workers * 5
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(items), chunk_size):
            if time.monotonic() > deadline:
                break
            chunk = items[start:start + chunk_size]
            answers = pool.map(lambda item: claude_extract(client, item[1], item[2]), chunk)
            for (h, _, _), answer in zip(chunk, answers):
                if answer:
                    results.append({"text_hash": h, **answer})
    return results


def cost(results):
    return sum(r["input_tokens"] * PRICE_IN + r["output_tokens"] * PRICE_OUT for r in results)


# ---------------------------------------------------------------- the daily step

def _load_cache(con, cache_path):
    """Cached answers by text hash. Answers from an older prompt are dropped, so they're redone."""
    cache = {}
    if cache_path.exists():
        result = con.execute(f"SELECT * FROM read_parquet('{cache_path.as_posix()}')")
        columns = [d[0] for d in result.description]
        for row in result.fetchall():
            entry = dict(zip(columns, row))
            if entry.get("prompt_version") == PROMPT_VERSION:
                cache[entry["text_hash"]] = entry
    return cache


def extract_drugs(con, recall_drugs_path, recalls_path, cache_path, workdir, client=None,
                  max_calls=3000, seconds=900):
    """Claude's drug for every recall matching couldn't name. Returns a dict with the keys
    to give matching, the queue and cache (for write_review), and stats."""
    queue = con.execute(f"""
        SELECT r.recall_number, r.recalling_firm, r.product_description
        FROM read_parquet('{recalls_path.as_posix()}') r
        JOIN read_parquet('{recall_drugs_path.as_posix()}') d ON d.recall_number = r.recall_number
        WHERE d.drug_key IS NULL
        ORDER BY r.recall_number
    """).fetchall()
    cache = _load_cache(con, cache_path)

    todo = {}
    for _, firm, description in queue:
        h = text_hash(firm, description)
        if description and h not in cache:
            todo.setdefault(h, (h, firm, description))
    new = []
    if client and todo:
        new = extract_many(client, list(todo.values())[:max_calls], seconds)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in new:
            cache[r["text_hash"]] = {
                "text_hash": r["text_hash"], "ingredients": json.dumps(r["ingredients"]),
                "drug_key": r["drug_key"], "strength": r["strength"],
                "dosage_form": r["dosage_form"], "compounded": r["compounded"],
                "confidence": r["confidence"], "model": MODEL,
                "prompt_version": PROMPT_VERSION, "extracted_at": stamp}

    if cache:
        load_batch(con, list(cache.values()), CACHE_COLUMNS, "claude_drugs", workdir)
    else:   # nothing asked yet, so write an empty table with the right columns
        con.execute("CREATE OR REPLACE TABLE claude_drugs ("
                    + ", ".join(f"{c} VARCHAR" for c in CACHE_COLUMNS) + ")")
    write_parquet(con, "SELECT * FROM claude_drugs ORDER BY text_hash", cache_path)

    keys, answered = {}, 0
    for number, firm, description in queue:
        entry = cache.get(text_hash(firm, description))
        if entry:
            answered += 1
            if entry["drug_key"] and entry["confidence"] in USE_CONFIDENCE:
                keys[number] = entry["drug_key"]
    return {"keys": keys, "queue": queue, "cache": cache, "stats": {
        "queue": len(queue),
        "answered": answered,
        "waiting": len(queue) - answered,
        "calls": len(new),
        "cost": round(cost(new), 4),
    }}


def write_review(con, extraction, recall_drugs_path, review_path):
    """After the second matching pass: Claude's answers that matching didn't use, and why."""
    used = {n for (n,) in con.execute(
        f"SELECT recall_number FROM read_parquet('{recall_drugs_path.as_posix()}') "
        "WHERE id_source = 'claude'").fetchall()}
    order = {"not a known drug name": 0, "low confidence": 1, "no drug named": 2}
    rows = []
    for number, firm, description in extraction["queue"]:
        entry = extraction["cache"].get(text_hash(firm, description))
        if not entry or number in used:
            continue
        if not entry["drug_key"]:
            problem = "no drug named"
        elif entry["confidence"] not in USE_CONFIDENCE:
            problem = "low confidence"
        else:
            problem = "not a known drug name"
        rows.append({"recall_number": number, "recalling_firm": firm,
                     "product_description": (description or "")[:300],
                     "ingredients": ", ".join(json.loads(entry["ingredients"] or "[]")),
                     "confidence": entry["confidence"], "problem": problem})
    rows.sort(key=lambda r: (order[r["problem"]], r["recall_number"]))
    with open(review_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return {problem: sum(1 for r in rows if r["problem"] == problem) for problem in order}


# ---------------------------------------------------------------- scoring against the audit

# For scoring only. Recall text often leaves the salt off ("fentaNYL in 0.9% sodium
# chloride"), so a hand label of fentanyl and Claude's fentanyl citrate are the same drug.
SALTS = {"hydrochloride", "dihydrochloride", "hydrobromide", "hcl", "sulfate", "bisulfate",
         "citrate", "sodium", "disodium", "potassium", "calcium", "magnesium", "acetate",
         "phosphate", "mesylate", "maleate", "tartrate", "bitartrate", "succinate", "fumarate",
         "besylate", "bromide", "chloride", "lactate", "gluconate", "tromethamine", "hyclate",
         "pamoate", "nitrate", "monohydrate", "dihydrate", "trihydrate", "anhydrous"}
SAME_SUBSTANCE = {"ethyl alcohol": "alcohol", "ethanol": "alcohol", "dehydrated alcohol": "alcohol"}


def base_key(key):
    """A drug key with the salt words dropped, so fentanyl citrate and fentanyl match.
    A part that is only salt words, like sodium chloride, stays whole."""
    if not key:
        return key
    parts = set()
    for part in key.split(" + "):
        part = SAME_SUBSTANCE.get(part, part)
        words = [w for w in part.split() if w not in SALTS]
        parts.add(" ".join(words) if words else part)
    return " + ".join(sorted(parts))


def score_extractions(rows):
    """rows are dicts with truth, pipeline (what matching found), claude (Claude's key after
    the known-drug and confidence checks) and raw (Claude's key before them).

    Claude only runs when matching found nothing, so the pipeline's answer always wins.
    """
    misses = [r for r in rows if not r["pipeline"]]
    return {
        "rows": len(rows),
        "before": sum(1 for r in rows if r["pipeline"] == r["truth"]),
        "after": sum(1 for r in rows if (r["pipeline"] or r["claude"]) == r["truth"]),
        "misses": len(misses),
        "fixed": [r for r in misses if r["claude"] == r["truth"]],
        "wrong": [r for r in misses if r["claude"] and r["claude"] != r["truth"]],
        "unused": [r for r in misses if not r["claude"]],
        "alone": sum(1 for r in rows if r["raw"] == r["truth"]),
    }


def _pct(part, whole):
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def _load_eval_cache():
    if not EVAL_CACHE.exists():
        return {}
    with open(EVAL_CACHE, newline="", encoding="utf-8") as f:
        return {r["text_hash"]: r for r in csv.DictReader(f)
                if r.get("prompt_version") == PROMPT_VERSION}


def report_eval():
    """Score Claude on the audited recalls where you said which drug it is."""
    import duckdb

    # The sheet, not answer_key.csv, because it also has the firm, the product text, and
    # the drug the pipeline found back when you audited it.
    if not SHEET_PATH.exists():
        sys.exit("audit/audit_sheet.xlsx is missing. Run python -m shortagesignal.audit sample first.")
    audit = [r for r in read_sheet(SHEET_PATH) if r.get("drug_ok") in ("yes", "no")]
    for path in (NDC_PATH, SNAPSHOTS_PATH, RECALLS_PATH):
        if not path.exists():
            sys.exit(f"{path} is missing. Copy the data branch in first: "
                     "git fetch origin data, then git archive origin/data | tar -x -C data")

    con = duckdb.connect()
    known, brand_map = known_drugs(con, NDC_PATH, SNAPSHOTS_PATH, RECALLS_PATH)
    cache = _load_eval_cache()
    todo = {}
    for r in audit:
        h = text_hash(r.get("firm"), r.get("product_description"))
        if h not in cache and r.get("product_description"):
            todo.setdefault(h, (h, r.get("firm"), r["product_description"]))
    new = []
    if todo:
        client = make_client()
        if not client:
            sys.exit("ANTHROPIC_API_KEY isn't set. Add it as a Codespaces secret, then reopen "
                     "the codespace.")
        print(f"Asking Claude about {len(todo)} audit rows...")
        new = extract_many(client, list(todo.values()), seconds=600)
        for r in new:
            cache[r["text_hash"]] = {**r, "ingredients": json.dumps(r["ingredients"]),
                                     "prompt_version": PROMPT_VERSION}
        EVAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(EVAL_CACHE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CACHE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(cache.values())

    rows, by_conf = [], {}
    for r in audit:
        truth = r.get("drug_found") if r["drug_ok"] == "yes" else drug_key(r.get("correct_drug"))
        if not truth:
            continue
        entry = cache.get(text_hash(r.get("firm"), r.get("product_description"))) or {}
        raw, conf = entry.get("drug_key") or None, entry.get("confidence", "")
        used = check_claude_key(raw, known, brand_map) if conf in USE_CONFIDENCE else None
        rows.append({"recall_number": r["recall_number"], "truth": truth,
                     "pipeline": r.get("drug_found") or None, "raw": raw, "claude": used,
                     "confidence": conf, "description": r.get("product_description")})
        if raw:
            exact_right, loose_right, total = by_conf.get(conf, (0, 0, 0))
            by_conf[conf] = (exact_right + (raw == truth),
                             loose_right + (base_key(raw) == base_key(truth)), total + 1)

    exact = score_extractions(rows)
    s = score_extractions([{**r, **{k: base_key(r[k]) for k in ("truth", "pipeline", "claude", "raw")}}
                           for r in rows])
    n = s["rows"]

    def both(name, key):
        return (f"| {name} | {exact[key]} of {n} ({_pct(exact[key], n)}) "
                f"| {s[key]} of {n} ({_pct(s[key], n)}) |")

    lines = [
        "# Drug extraction results", "",
        f"Scored against the {n} audited recalls where the drug is clear. Claude only runs "
        "when matching names no drug, so the pipeline's own answer always wins. Recall text "
        "often leaves the salt off, so the second column counts fentanyl and fentanyl "
        "citrate as the same drug.", "",
        "| | Exact name | Ignoring salts |", "|---|---|---|",
        both("Finds the drug, before Claude", "before"),
        both("Finds the drug, with Claude", "after"),
        both("Claude alone, before any checks", "alone"), "",
        f"On the {s['misses']} recalls matching couldn't name, ignoring salts, Claude's "
        f"checked answer was right for {len(s['fixed'])}, wrong for {len(s['wrong'])}, and "
        f"not used for {len(s['unused'])} (no drug named, low confidence, or not a known drug).",
        "", "## Claude by confidence, before the checks", "",
        "| Confidence | Exact name | Ignoring salts |", "|---|---|---|",
        *[f"| {c} | {e} of {t} ({_pct(e, t)}) | {lo} of {t} ({_pct(lo, t)}) |"
          for c, (e, lo, t) in sorted(by_conf.items())],
        "", f"Model: {MODEL}. This run's new calls cost about ${cost(new):.4f}.",
    ]
    EVAL_RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    original = {r["recall_number"]: r for r in rows}
    for title, group in (("Wrong drug added", s["wrong"]), ("Not used", s["unused"])):
        if group:
            print(f"\n{title}, ignoring salts ({len(group)}): Claude said → you said")
            for r in group:
                o = original[r["recall_number"]]
                print(f"  {o['recall_number']}: {o['raw'] or '(nothing)'} [{o['confidence']}] → "
                      f"{o['truth']} | {(o['description'] or '')[:70]}")
    print(f"\nSaved {EVAL_RESULTS}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["eval"]:
        report_eval()
    else:
        sys.exit("usage: python -m shortagesignal.extract eval")


if __name__ == "__main__":
    main()
