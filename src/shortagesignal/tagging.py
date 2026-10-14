"""
Day 8: root-cause tagging, scored against your hand audit.

  python -m shortagesignal.tagging rules   score sql/root_cause_rules.sql against the answer key
  python -m shortagesignal.tagging eval    score rules, Claude, and rules-then-Claude on the 99 audit rows

How a recall gets its root cause:
  1. The rules in sql/root_cause_rules.sql. Free, instant, easy to check.
  2. Whatever the rules leave untagged goes to Claude Haiku, which must answer by calling
     a tool whose schema only allows the 12 category names. The same reason text always
     gets the same answer, so each distinct reason is asked once, and answers are cached.
  3. Claude's unsure answers (low or medium confidence) also land in tag_review.csv for
     a person to check, one row per distinct reason with how many recalls it covers. The
     audit showed medium is right only about half the time.

The daily run only calls Claude when SHORTAGESIGNAL_USE_CLAUDE=1 (set in GitHub Actions),
so local test runs never spend money by accident.
"""
import csv
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import duckdb

from shortagesignal.audit import ROOT_CAUSES
from shortagesignal.config import ROOT
from shortagesignal.run_sql import connect, read_query
from shortagesignal.storage import load_batch, write_parquet

RULES_PATH = ROOT / "sql" / "root_cause_rules.sql"
EVAL_CACHE = ROOT / "audit" / "claude_eval_tags.csv"
EVAL_RESULTS = ROOT / "audit" / "tagging_results.md"
CATEGORIES = set(ROOT_CAUSES)
MODEL = "claude-haiku-5-5"
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6   # dollars per token, Haiku 5.5 list price
CACHE_COLUMNS = ["recall_number", "reason_hash", "root_cause", "confidence", "why", "model",
                 "prompt_version", "tagged_at"]
REVIEW_CONFIDENCE = {"low", "medium"}   # the audit showed medium is right only about half the time

SYSTEM_PROMPT = "\n".join([
    "You label why an FDA drug recall happened. Read the recall's reason and pick exactly one",
    "root cause from this list.",
    "",
    *[f"- {name}: {definition}" for name, definition in ROOT_CAUSES.items()],
    "",
    "Rules:",
    "1. When the reason names a specific problem that has its own category, pick that category,",
    "   even if the reason also says CGMP or 'out of specification'. 'CGMP Deviations: presence",
    "   of NDMA impurity' is Impurities. 'Subpotent drug out of specification' is Potency.",
    "2. Process failures that aren't a finding about the product itself stay CGMP: monitoring,",
    "   investigations, procedures, insanitary conditions, 'Lack of Processing Controls', and",
    "   storage or temperature problems.",
    "3. Pick Sterility only when the reason is about the product: it can't be shown to be sterile,",
    "   or a sterile product was contaminated.",
    "4. Bacteria, mold or yeast in a non-sterile product is Microbial contamination.",
    "5. Foreign tablets or capsules (the wrong pill in the bottle) is Labeling or packaging.",
    "   A foreign substance is Chemical or foreign contamination.",
    "6. Plain discoloration, a change in color, or an atypical appearance is Failed",
    "   specification, unless the reason names a cause.",
    "7. When FDA's label is CGMP and the reason only describes a risk, not something found in",
    "   this product, keep CGMP: 'made at the same facility as', 'manufactured under the same",
    "   conditions as products found subpotent', 'conditions that could', 'potential",
    "   contamination', 'a water system lacking controls'.",
    "8. When two categories both fit, go with the label FDA wrote at the start of the reason.",
    "9. Use Other only when nothing fits.",
    "",
    "Confidence: high when the reason clearly fits one category, medium when you had to choose",
    "between two, low when the reason is vague.",
])
# Changes whenever the prompt or model changes, so old cached answers get redone.
PROMPT_VERSION = hashlib.md5((MODEL + SYSTEM_PROMPT).encode()).hexdigest()[:8]
TAG_TOOL = {
    "name": "record_root_cause",
    "description": "Record the root cause of one drug recall.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {"type": "string", "enum": list(ROOT_CAUSES)},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "why": {"type": "string", "description": "A few words on why"},
        },
        "required": ["root_cause", "confidence", "why"],
    },
}


# ---------------------------------------------------------------- scoring

def score_tags(rows):
    """rows are (recall_number, reason, hand_label, tag). Returns coverage, accuracy and misses."""
    labeled = [r for r in rows if r[2]]
    tagged = [r for r in labeled if r[3]]
    right = [r for r in tagged if r[3] == r[2]]
    return {
        "labeled": len(labeled),
        "tagged": len(tagged),
        "right": len(right),
        "wrong": [r for r in tagged if r[3] != r[2]],
        "untagged": [r for r in labeled if not r[3]],
        "bad_names": sorted({r[3] for r in rows if r[3] and r[3] not in CATEGORIES}),
    }


def _pct(part, whole):
    return f"{round(100 * part / whole)}%" if whole else "n/a"


# ---------------------------------------------------------------- Claude

def make_client():
    """An Anthropic client, or None when there's no API key."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic(max_retries=6)   # retries rate limits with backoff


def reason_hash(reason):
    return hashlib.md5((reason or "").encode()).hexdigest()


def claude_tag(client, reason):
    """Ask Claude for one recall's root cause. None if the call fails or the answer is off-list."""
    try:
        message = client.messages.create(
            model=MODEL, max_tokens=200, system=SYSTEM_PROMPT,
            tools=[TAG_TOOL], tool_choice={"type": "tool", "name": TAG_TOOL["name"]},
            messages=[{"role": "user", "content": f"Reason for recall: {reason}"}],
        )
    except Exception as exc:   # one bad call shouldn't stop the run
        print(f"    Claude call failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    for block in message.content:
        if getattr(block, "type", "") == "tool_use":
            answer = block.input
            if answer.get("root_cause") in CATEGORIES:
                return {"root_cause": answer["root_cause"],
                        "confidence": answer.get("confidence", "low"),
                        "why": str(answer.get("why", ""))[:200],
                        "input_tokens": message.usage.input_tokens,
                        "output_tokens": message.usage.output_tokens}
    return None


def tag_many(client, items, seconds=900, workers=4):
    """Tag (recall_number, reason) pairs a few at a time, stopping when the time runs out."""
    results, deadline, chunk_size = [], time.monotonic() + seconds, workers * 5
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(items), chunk_size):
            if time.monotonic() > deadline:
                break
            chunk = items[start:start + chunk_size]
            answers = pool.map(lambda item: claude_tag(client, item[1]), chunk)
            for (number, reason), answer in zip(chunk, answers):
                if answer:
                    results.append({"recall_number": number, "reason_hash": reason_hash(reason),
                                    **answer})
    return results


def cost(results):
    return sum(r["input_tokens"] * PRICE_IN + r["output_tokens"] * PRICE_OUT for r in results)


# ---------------------------------------------------------------- the daily step

def _rule_rows(recalls_path):
    """(recall_number, reason, rule tag) for every recall, using sql/root_cause_rules.sql."""
    con = duckdb.connect()
    con.execute(f"CREATE VIEW recalls AS SELECT * FROM read_parquet('{recalls_path.as_posix()}')")
    rules = read_query(RULES_PATH)
    return con, con.execute(f"""
        SELECT r.recall_number, r.reason_for_recall, t.root_cause_rule
        FROM recalls r JOIN (
{rules}
        ) t ON t.recall_number = r.recall_number
    """).fetchall()


def build_root_causes(recalls_path, cache_path, out_path, review_path, workdir, client=None,
                      max_calls=2000, seconds=900):
    """Tag every recall: rules first, then cached Claude answers, then new Claude calls."""
    con, rows = _rule_rows(recalls_path)
    cache = {}
    if cache_path.exists():
        result = con.execute(f"SELECT * FROM read_parquet('{cache_path.as_posix()}')")
        columns = [d[0] for d in result.description]
        for row in result.fetchall():
            entry = dict(zip(columns, row))
            # Answers from an older prompt are redone, so every tag follows today's rules.
            if entry.get("prompt_version") == PROMPT_VERSION:
                cache[(entry["recall_number"], entry["reason_hash"])] = entry

    # The same reason text gets the same answer, so a reason Claude has already seen is
    # answered from the cache, and each new reason is asked once for all its recalls.
    seen = {}
    for entry in cache.values():
        seen.setdefault(entry["reason_hash"], entry)
    waiting = {}   # reason hash -> recall numbers with that reason
    todo = {}      # reason hash -> one (recall number, reason) to ask Claude about
    for n, reason, rule in rows:
        h = reason_hash(reason)
        if rule or (n, h) in cache:
            continue
        if h in seen:
            cache[(n, h)] = {**seen[h], "recall_number": n}
        else:
            waiting.setdefault(h, []).append(n)
            todo.setdefault(h, (n, reason))
    new = []
    if client and todo:
        new = tag_many(client, list(todo.values())[:max_calls], seconds)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in new:
            for n in waiting[r["reason_hash"]]:
                cache[(n, r["reason_hash"])] = {
                    "recall_number": n, "reason_hash": r["reason_hash"],
                    "root_cause": r["root_cause"], "confidence": r["confidence"],
                    "why": r["why"], "model": MODEL, "prompt_version": PROMPT_VERSION,
                    "tagged_at": stamp}

    final, review = [], {}
    for number, reason, rule in rows:
        cached = cache.get((number, reason_hash(reason)))
        if rule:
            final.append({"recall_number": number, "root_cause": rule, "source": "rule",
                          "confidence": "", "why": ""})
        elif cached:
            final.append({"recall_number": number, "root_cause": cached["root_cause"],
                          "source": "claude", "confidence": cached["confidence"],
                          "why": cached["why"]})
            if cached["confidence"] in REVIEW_CONFIDENCE:
                group = review.setdefault(cached["reason_hash"], {
                    "reason_for_recall": reason, "recalls": 0, "example_recall": number,
                    **{k: cached[k] for k in ("root_cause", "confidence", "why")}})
                group["recalls"] += 1
        else:
            final.append({"recall_number": number, "root_cause": None, "source": None,
                          "confidence": "", "why": ""})

    if cache:
        load_batch(con, list(cache.values()), CACHE_COLUMNS, "claude_tags", workdir)
    else:   # nothing tagged by Claude yet, so write an empty table with the right columns
        con.execute("CREATE OR REPLACE TABLE claude_tags ("
                    + ", ".join(f"{c} VARCHAR" for c in CACHE_COLUMNS) + ")")
    write_parquet(con, "SELECT * FROM claude_tags ORDER BY recall_number", cache_path)
    load_batch(con, final, ["recall_number", "root_cause", "source", "confidence", "why"],
               "root_causes", workdir)
    write_parquet(con, "SELECT * FROM root_causes ORDER BY recall_number", out_path)
    with open(review_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["reason_for_recall", "recalls", "root_cause",
                                               "confidence", "why", "example_recall"])
        writer.writeheader()
        writer.writerows(sorted(review.values(), key=lambda g: -g["recalls"]))

    tagged = sum(1 for r in final if r["root_cause"])
    return {
        "recalls": len(final),
        "tagged": tagged,
        "tagged_pct": round(100 * tagged / len(final), 1) if final else 0.0,
        "by_rule": sum(1 for r in final if r["source"] == "rule"),
        "by_claude": sum(1 for r in final if r["source"] == "claude"),
        "backlog": len(final) - tagged,
        "claude_calls": len(new),
        "claude_cost": round(cost(new), 4),
        "to_review": len(review),
        "to_review_recalls": sum(g["recalls"] for g in review.values()),
    }


# ---------------------------------------------------------------- command line

def _audit_rows(con):
    """(recall_number, reason, hand label, rule tag) for every row of the answer key."""
    rules = read_query(RULES_PATH)
    con.execute(f"CREATE OR REPLACE TEMP VIEW rule_tags AS\n{rules}\n")
    return con.execute("""
        SELECT k.recall_number, k.reason_for_recall, k.root_cause, t.root_cause_rule
        FROM answer_key k LEFT JOIN rule_tags t ON t.recall_number = k.recall_number
    """).fetchall()


def report_rules():
    con = connect()
    rows = _audit_rows(con)
    total, tagged_all = con.execute(
        "SELECT count(*), count(root_cause_rule) FROM rule_tags").fetchone()
    s = score_tags(rows)
    print(f"All recalls: the rules tag {tagged_all:,} of {total:,} ({_pct(tagged_all, total)})")
    print(f"Your audit:  the rules tag {s['tagged']} of {s['labeled']} "
          f"({_pct(s['tagged'], s['labeled'])}), "
          f"and {s['right']} of those {s['tagged']} are right ({_pct(s['right'], s['tagged'])})")
    if s["bad_names"]:
        print("\nNot one of the 12 category names (check the spelling): " + ", ".join(s["bad_names"]))
    if s["wrong"]:
        print(f"\nWrong ({len(s['wrong'])}): rule said → you said")
        for number, reason, hand, tag in s["wrong"]:
            print(f"  {number}: {tag} → {hand} | {reason[:90]}")
    if s["untagged"]:
        print(f"\nNot tagged by any rule ({len(s['untagged'])}), these go to Claude:")
        for number, reason, hand, _ in s["untagged"][:15]:
            print(f"  {number}: you said {hand} | {reason[:90]}")


def _load_eval_cache():
    if not EVAL_CACHE.exists():
        return {}
    with open(EVAL_CACHE, newline="", encoding="utf-8") as f:
        return {(r["recall_number"], r["reason_hash"]): r for r in csv.DictReader(f)
                if r.get("prompt_version") == PROMPT_VERSION}


def report_eval():
    """Rules, Claude alone, and rules-then-Claude, all scored on the same audit rows."""
    con = connect()
    rows = [r for r in _audit_rows(con) if r[2]]
    cache = _load_eval_cache()
    todo = [(n, reason) for n, reason, _, _ in rows if (n, reason_hash(reason)) not in cache]
    new = []
    if todo:
        client = make_client()
        if not client:
            sys.exit("ANTHROPIC_API_KEY isn't set. Add it as a Codespaces secret, then reopen "
                     "the codespace.")
        print(f"Asking Claude about {len(todo)} audit rows...")
        new = tag_many(client, todo, seconds=600)
        for r in new:
            key = (r["recall_number"], r["reason_hash"])
            cache[key] = {**r, "prompt_version": PROMPT_VERSION}
        EVAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(EVAL_CACHE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["recall_number", "reason_hash", "root_cause",
                                                   "confidence", "why", "prompt_version"],
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(cache.values())

    def claude_for(n, reason):
        hit = cache.get((n, reason_hash(reason)))
        return (hit["root_cause"], hit["confidence"]) if hit else (None, None)

    rules = score_tags(rows)
    alone = score_tags([(n, reason, hand, claude_for(n, reason)[0]) for n, reason, hand, _ in rows])
    rest = [(n, reason, hand, claude_for(n, reason)[0]) for n, reason, hand, rule in rows if not rule]
    on_rest = score_tags(rest)
    both = score_tags([(n, reason, hand, rule or claude_for(n, reason)[0])
                       for n, reason, hand, rule in rows])
    by_conf = {}
    for n, reason, hand, _ in rows:
        tag, conf = claude_for(n, reason)
        if tag:
            right, total = by_conf.get(conf, (0, 0))
            by_conf[conf] = (right + (tag == hand), total + 1)

    def line(name, s):
        return (f"| {name} | {s['tagged']} of {s['labeled']} | "
                f"{s['right']} of {s['tagged']} ({_pct(s['right'], s['tagged'])}) |")

    lines = [
        "# Root-cause tagging results", "",
        f"Scored against the {len(rows)} hand-labeled audit recalls.", "",
        "| Tagger | Tags | Right |", "|---|---|---|",
        line("Rules (sql/root_cause_rules.sql)", rules),
        line("Claude alone", alone),
        line("Claude, on the recalls the rules couldn't tag", on_rest),
        line("Rules first, then Claude", both),
        "", "## Claude by confidence", "", "| Confidence | Right |", "|---|---|",
        *[f"| {conf} | {r} of {t} ({_pct(r, t)}) |" for conf, (r, t) in sorted(by_conf.items())],
        "", f"Model: {MODEL}. This run's new calls cost about ${cost(new):.4f}.",
    ]
    EVAL_RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if alone["wrong"]:
        print(f"\nClaude was wrong on {len(alone['wrong'])}: Claude said → you said")
        for number, reason, hand, tag in alone["wrong"]:
            print(f"  {number}: {tag} → {hand} | {reason[:90]}")
    print(f"\nSaved {EVAL_RESULTS}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["rules"]:
        report_rules()
    elif args[:1] == ["eval"]:
        report_eval()
    else:
        sys.exit("usage: python -m shortagesignal.tagging rules | eval")


if __name__ == "__main__":
    main()
