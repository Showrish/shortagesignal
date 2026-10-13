"""Root-cause tagging: the scorer, the rules SQL, and the Claude step with a fake client."""
import csv
from types import SimpleNamespace

import duckdb

from shortagesignal import tagging
from shortagesignal.run_sql import connect, read_query
from shortagesignal.tagging import (
    CATEGORIES,
    RULES_PATH,
    TAG_TOOL,
    build_root_causes,
    claude_tag,
    score_tags,
    tag_many,
)


class FakeClient:
    """Stands in for the Anthropic client, so tests never call the real API."""

    def __init__(self, answer="Other", fail=False, confidence="low"):
        self.calls, self.answer, self.fail, self.confidence = 0, answer, fail, confidence
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("rate limited")
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={
                "root_cause": self.answer, "confidence": self.confidence, "why": "test"})],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50))


def test_score_tags_counts_coverage_accuracy_and_misses():
    rows = [
        ("D-1", "Lack of Assurance of Sterility", "Sterility", "Sterility"),   # right
        ("D-2", "CGMP Deviations: NDMA impurity", "Impurities", "CGMP"),       # wrong
        ("D-3", "Some unusual reason", "Other", None),                         # untagged
        ("D-4", "Not in the audit", "", "CGMP"),                               # not labeled
        ("D-5", "Typo in a rule", "Potency", "Potentcy"),                      # bad name
    ]
    s = score_tags(rows)
    assert (s["labeled"], s["tagged"], s["right"]) == (4, 3, 1)
    assert [r[0] for r in s["wrong"]] == ["D-2", "D-5"]
    assert [r[0] for r in s["untagged"]] == ["D-3"]
    assert s["bad_names"] == ["Potentcy"]


RULE_CASES = [
    ("Lack of Assurance of Sterility", "Sterility"),
    ("Microbial contamination of non-sterile product.", "Microbial contamination"),
    ("CGMP Deviations: Presence of NDMA impurity detected in product.", "Impurities"),
    ("cGMP deviations: Temperature abuse", "CGMP"),
    ("Lack of Processing Controls: Insanitary conditions observed during compounding of "
     "sterile drugs during recent FDA Inspection.", "CGMP"),
    ("Subpotent Drug: assay below the labeled amount", "Potency"),
    ("Presence of Foreign Tablets/Capsules", "Labeling or packaging"),
    ("Presence of a foreign substance", "Chemical or foreign contamination"),
    ("Presence of particulate matter", "Particulates"),
    ("Discoloration", "Failed specification"),
    ("Defective Delivery System", "Container or device defect"),
    ("Marketed Without An Approved NDA/ANDA", "Unapproved drug"),
    ("Labeling: Not Elsewhere Classified", "Labeling or packaging"),
    ("Something unusual the rules have never seen", None),
    # Precautionary CGMP recalls: nothing was found in this product.
    ("CGMP Deviations: manufactured under the same conditions as those found to be subpotent.",
     "CGMP"),
    ("CGMP Deviations: product manufactured at the same facility that produced product that "
     "FDA found contaminated", "CGMP"),
    ("CGMP Deviations: products manufactured by contract manufacturer under conditions that "
     "could lead to microbial contamination", "CGMP"),
    ("cGMP Deviations: Potential product contamination with Burkholderia cepacia", "CGMP"),
    ("CGMP Deviations: product manufactured using deionized water from a system lacking "
     "appropriate controls", "CGMP"),
    # But a CGMP label with a real finding still goes to the specific category.
    ("CGMP Deviations: Out of Specification results for total microbial count",
     "Microbial contamination"),
    ("CGMP Deviations: These products have been found to be misbranded as unapproved new drugs",
     "Unapproved drug"),
    ("Lack of Assurance of Sterility: potential microbial contamination", "Sterility"),
    # Particle size is a specification, not particles in the product.
    ("Failed Tablet/Capsule Specifications: Out of Specification results for particle Size "
     "Distribution", "Failed specification"),
    ("cGMP deviations: Atypical appearance, decrease in size and change in color of the "
     "lyophilized cake", "Failed specification"),
]


def test_rules_sql_tags_the_audit_cases_correctly():
    """Runs sql/root_cause_rules.sql, so a rule edit that breaks one of these fails CI."""
    con = duckdb.connect()
    values = ", ".join(f"('D-{i}', '{reason}')" for i, (reason, _) in enumerate(RULE_CASES))
    con.execute(f"CREATE VIEW recalls AS SELECT * FROM (VALUES {values}) "
                "t(recall_number, reason_for_recall)")
    rel = con.sql(read_query(RULES_PATH))
    assert rel.columns == ["recall_number", "root_cause_rule"]
    tags = dict(rel.fetchall())
    for i, (reason, expected) in enumerate(RULE_CASES):
        assert tags[f"D-{i}"] == expected, reason
    assert {t for t in tags.values() if t} <= CATEGORIES


def test_connect_finds_tables_by_short_name(tmp_path):
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 'D-1' AS recall_number) TO "
                f"'{(tmp_path / 'recalls.parquet').as_posix()}' (FORMAT PARQUET)")
    (tmp_path / "answer_key.csv").write_text("recall_number,root_cause\nD-1,CGMP\n")
    con = connect(tmp_path, tmp_path)
    assert con.sql("SELECT * FROM recalls").fetchall() == [("D-1",)]
    assert con.sql("SELECT root_cause FROM answer_key").fetchall() == [("CGMP",)]


def test_the_tool_only_allows_the_12_categories():
    allowed = TAG_TOOL["input_schema"]["properties"]["root_cause"]["enum"]
    assert set(allowed) == CATEGORIES and len(allowed) == 12


def test_claude_tag_reads_the_tool_call_and_survives_errors():
    answer = claude_tag(FakeClient(answer="Sterility"), "Lack of Assurance of Sterility")
    assert answer["root_cause"] == "Sterility" and answer["input_tokens"] == 1000
    assert claude_tag(FakeClient(fail=True), "anything") is None
    assert claude_tag(FakeClient(answer="Not a category"), "anything") is None


def test_tag_many_stops_when_the_time_is_up():
    client = FakeClient()
    assert tag_many(client, [("D-1", "a"), ("D-2", "b")], seconds=-1) == []
    assert client.calls == 0


def test_build_root_causes_uses_rules_then_claude_then_the_cache(tmp_path):
    con = duckdb.connect()
    recalls = tmp_path / "recalls.parquet"
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('D-1', 'Lack of Assurance of Sterility'),
        ('D-2', 'CGMP Deviations'),
        ('D-3', 'Something unusual the rules have never seen')
    ) t(recall_number, reason_for_recall)) TO '{recalls.as_posix()}' (FORMAT PARQUET)""")
    paths = (tmp_path / "claude_tags.parquet", tmp_path / "root_causes.parquet",
             tmp_path / "tag_review.csv")
    client = FakeClient(answer="Other")

    first = build_root_causes(recalls, *paths, tmp_path, client=client)
    assert (first["by_rule"], first["by_claude"], first["backlog"]) == (2, 1, 0)
    assert client.calls == 1
    sources = dict(con.execute(
        f"SELECT recall_number, source FROM read_parquet('{paths[1].as_posix()}')").fetchall())
    assert sources == {"D-1": "rule", "D-2": "rule", "D-3": "claude"}
    with open(paths[2], newline="") as f:
        assert [r["recall_number"] for r in csv.DictReader(f)] == ["D-3"]   # low confidence

    second = build_root_causes(recalls, *paths, tmp_path, client=client)
    assert second["by_claude"] == 1 and client.calls == 1   # answered from the cache


def test_no_client_means_no_calls_and_a_backlog(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert tagging.make_client() is None


def test_build_root_causes_without_claude_leaves_a_backlog(tmp_path):
    con = duckdb.connect()
    recalls = tmp_path / "recalls.parquet"
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('D-1', 'Lack of Assurance of Sterility'),
        ('D-2', 'Something unusual the rules have never seen')
    ) t(recall_number, reason_for_recall)) TO '{recalls.as_posix()}' (FORMAT PARQUET)""")
    stats = build_root_causes(recalls, tmp_path / "claude_tags.parquet",
                              tmp_path / "root_causes.parquet", tmp_path / "tag_review.csv",
                              tmp_path, client=None)
    assert (stats["by_rule"], stats["backlog"], stats["claude_calls"]) == (1, 1, 0)
    assert (tmp_path / "claude_tags.parquet").exists()


def test_old_prompt_answers_are_redone_and_unsure_ones_go_to_review(tmp_path):
    con = duckdb.connect()
    recalls, cache = tmp_path / "recalls.parquet", tmp_path / "claude_tags.parquet"
    con.execute(f"""COPY (SELECT * FROM (VALUES ('D-1', 'Something odd'), ('D-2', 'Odd too'))
                 t(recall_number, reason_for_recall)) TO '{recalls.as_posix()}' (FORMAT PARQUET)""")
    stale = [{"recall_number": "D-1", "reason_hash": tagging.reason_hash("Something odd"),
              "root_cause": "Other", "confidence": "high", "why": "", "model": tagging.MODEL,
              "prompt_version": "oldprompt", "tagged_at": ""}]
    tagging.load_batch(con, stale, tagging.CACHE_COLUMNS, "claude_tags", tmp_path)
    tagging.write_parquet(con, "SELECT * FROM claude_tags", cache)

    client = FakeClient(answer="Sterility", confidence="medium")
    summary = tagging.build_root_causes(recalls, cache, tmp_path / "root_causes.parquet",
                                        tmp_path / "tag_review.csv", tmp_path, client=client)
    assert client.calls == 2                      # the old-prompt answer was asked again
    assert summary["to_review"] == 2              # medium confidence goes to review
    versions = con.execute(
        f"SELECT DISTINCT prompt_version FROM read_parquet('{cache.as_posix()}')").fetchall()
    assert versions == [(tagging.PROMPT_VERSION,)]
