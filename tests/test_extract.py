"""Claude drug extraction, with a fake client so tests never call the real API."""
import csv
import json
import threading
from types import SimpleNamespace

import duckdb

from shortagesignal.extract import (
    base_key,
    claude_extract,
    extract_drugs,
    key_from,
    score_extractions,
    write_review,
)
from shortagesignal.storage import load_batch, write_parquet


class FakeClient:
    """Answers by the first word it finds in the product text."""

    def __init__(self, answers=None, fail=False):
        self.calls, self.answers, self.fail = 0, answers or {}, fail
        self.messages, self.lock = self, threading.Lock()   # calls arrive from several threads

    def create(self, **kwargs):
        with self.lock:
            self.calls += 1
        if self.fail:
            raise RuntimeError("rate limited")
        text = kwargs["messages"][0]["content"]
        answer = next((a for word, a in self.answers.items() if word in text),
                      {"ingredients": [], "confidence": "low"})
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={
                "strength": "", "dosage_form": "injection", "compounded": False, **answer})],
            usage=SimpleNamespace(input_tokens=600, output_tokens=60))


def save(con, rows, path, workdir):
    columns = sorted({c for r in rows for c in r})
    load_batch(con, rows, columns, "fixture", workdir)
    write_parquet(con, "SELECT * FROM fixture", path)


def test_key_from_turns_ingredients_into_a_drug_key():
    assert key_from(["Amoxicillin", "Clavulanate Potassium"]) == "amoxicillin + clavulanate potassium"
    assert key_from(["Morphine Sulfate Injection"]) == "morphine sulfate"
    assert key_from([]) is None
    assert key_from(["  "]) is None


def test_claude_extract_reads_the_tool_answer():
    client = FakeClient({"Zantac": {"ingredients": ["Ranitidine Hydrochloride"],
                                    "confidence": "high", "dosage_form": "tablet"},
                         "Goo": {"ingredients": ["goo"], "confidence": "sure",
                                 "dosage_form": "goo"}})
    r = claude_extract(client, "Acme", "Zantac 150 mg tablets")
    assert r["ingredients"] == ["ranitidine hydrochloride"]
    assert r["drug_key"] == "ranitidine hydrochloride"
    assert (r["dosage_form"], r["compounded"], r["confidence"]) == ("tablet", "false", "high")

    odd = claude_extract(client, "Acme", "Goo")   # off-list answers fall back safely
    assert (odd["dosage_form"], odd["confidence"]) == ("unknown", "low")
    assert claude_extract(FakeClient(fail=True), "Acme", "Zantac") is None


def _queue(con, tmp_path):
    recalls, recall_drugs = tmp_path / "recalls.parquet", tmp_path / "recall_drugs.parquet"
    pharmacy = {"recalling_firm": "Main Street Pharmacy",
                "product_description": "Methylprednisolone acetate 80 mg/mL, compounded"}
    save(con, [
        {"recall_number": "D-1", **pharmacy},
        {"recall_number": "D-2", **pharmacy},   # same text as D-1
        {"recall_number": "D-3", "recalling_firm": "X Labs", "product_description": "Mystery powder"},
        {"recall_number": "D-4", "recalling_firm": "Y Labs",
         "product_description": "Unobtainium tablets"},
        {"recall_number": "D-5", "recalling_firm": "Hospira",
         "product_description": "Heparin Sodium Injection"},
    ], recalls, tmp_path)
    save(con, [
        {"recall_number": n, "drug_key": None, "id_source": None} for n in ("D-1", "D-2", "D-3", "D-4")
    ] + [{"recall_number": "D-5", "drug_key": "heparin sodium", "id_source": "text_name"}],
        recall_drugs, tmp_path)
    return recalls, recall_drugs


ANSWERS = {
    "Methylprednisolone": {"ingredients": ["methylprednisolone acetate"], "confidence": "high",
                           "compounded": True},
    "Mystery": {"ingredients": ["mysterine"], "confidence": "low"},
    "Unobtainium": {"ingredients": ["unobtainium"], "confidence": "high"},
}


def test_extract_drugs_asks_once_per_text_and_uses_only_sure_answers(tmp_path):
    con = duckdb.connect()
    recalls, recall_drugs = _queue(con, tmp_path)
    cache = tmp_path / "claude_drugs.parquet"
    client = FakeClient(ANSWERS)

    x = extract_drugs(con, recall_drugs, recalls, cache, tmp_path, client=client)
    assert client.calls == 3                   # D-1 and D-2 share a text, D-5 is already named
    assert x["keys"] == {"D-1": "methylprednisolone acetate", "D-2": "methylprednisolone acetate",
                         "D-4": "unobtainium"}  # D-3 was low confidence
    assert (x["stats"]["queue"], x["stats"]["answered"], x["stats"]["waiting"]) == (4, 4, 0)
    compounded = con.execute(
        f"SELECT compounded FROM read_parquet('{cache.as_posix()}') "
        "WHERE drug_key = 'methylprednisolone acetate'").fetchone()[0]
    assert compounded == "true"

    again = extract_drugs(con, recall_drugs, recalls, cache, tmp_path, client=client)
    assert client.calls == 3 and again["keys"] == x["keys"]          # all from the cache
    offline = extract_drugs(con, recall_drugs, recalls, cache, tmp_path, client=None)
    assert offline["keys"] == x["keys"]                               # no client needed


def test_write_review_says_why_an_answer_was_not_used(tmp_path):
    con = duckdb.connect()
    recalls, recall_drugs = _queue(con, tmp_path)
    x = extract_drugs(con, recall_drugs, recalls, tmp_path / "claude_drugs.parquet", tmp_path,
                      client=FakeClient(ANSWERS))
    # After the second matching pass: D-1 and D-2 used Claude's name, unobtainium didn't count.
    after = tmp_path / "recall_drugs_after.parquet"
    save(con, [
        {"recall_number": "D-1", "drug_key": "methylprednisolone acetate", "id_source": "claude"},
        {"recall_number": "D-2", "drug_key": "methylprednisolone acetate", "id_source": "claude"},
        {"recall_number": "D-3", "drug_key": None, "id_source": None},
        {"recall_number": "D-4", "drug_key": None, "id_source": None},
        {"recall_number": "D-5", "drug_key": "heparin sodium", "id_source": "text_name"},
    ], after, tmp_path)
    review = tmp_path / "extract_review.csv"

    counts = write_review(con, x, after, review)
    assert counts == {"not a known drug name": 1, "low confidence": 1, "no drug named": 0}
    with open(review, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["recall_number"], r["problem"]) for r in rows] == [
        ("D-4", "not a known drug name"), ("D-3", "low confidence")]
    assert rows[1]["ingredients"] == "mysterine"


def test_score_extractions_lets_the_pipeline_win():
    rows = [
        {"truth": "heparin sodium", "pipeline": "heparin sodium", "claude": None,
         "raw": "heparin sodium"},                                    # pipeline right
        {"truth": "carboplatin", "pipeline": None, "claude": "carboplatin",
         "raw": "carboplatin"},                                       # Claude fixed it
        {"truth": "morphine sulfate", "pipeline": None, "claude": "morphine",
         "raw": "morphine"},                                          # Claude added a wrong drug
        {"truth": "alprostadil", "pipeline": None, "claude": None, "raw": None},   # not used
        {"truth": "lidocaine", "pipeline": "lidocaine hydrochloride", "claude": None,
         "raw": "lidocaine"},                                         # pipeline wrong, Claude never asked
    ]
    s = score_extractions(rows)
    assert (s["rows"], s["before"], s["after"], s["misses"], s["alone"]) == (5, 1, 2, 3, 3)
    assert [len(s[k]) for k in ("fixed", "wrong", "unused")] == [1, 1, 1]


def test_cache_keeps_ingredients_as_json(tmp_path):
    con = duckdb.connect()
    recalls, recall_drugs = _queue(con, tmp_path)
    cache = tmp_path / "claude_drugs.parquet"
    extract_drugs(con, recall_drugs, recalls, cache, tmp_path, client=FakeClient(ANSWERS))
    stored = con.execute(
        f"SELECT ingredients FROM read_parquet('{cache.as_posix()}') "
        "WHERE drug_key = 'unobtainium'").fetchone()[0]
    assert json.loads(stored) == ["unobtainium"]


def test_base_key_ignores_salts_but_keeps_salt_only_drugs():
    assert base_key("fentanyl citrate") == base_key("fentanyl") == "fentanyl"
    assert base_key("glycine + sermorelin acetate") == "glycine + sermorelin"
    assert base_key("ethyl alcohol") == base_key("alcohol") == "alcohol"
    assert base_key("sodium chloride") == "sodium chloride"
    assert base_key("sodium chloride") != base_key("potassium chloride")
    assert base_key("levothyroxine sodium + liothyronine sodium") != base_key("thyroid")
    assert base_key(None) is None
