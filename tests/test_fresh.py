import duckdb

from shortagesignal.fresh import make_sheet, read_labels, sample_rows, score


def _parquet(con, path, rows):
    columns = list(rows[0])
    values = ", ".join("(" + ", ".join("NULL" if r[c] is None else f"'{r[c]}'" for c in columns) + ")"
                       for r in rows)
    con.execute(f"COPY (SELECT * FROM (VALUES {values}) AS t({', '.join(columns)})) "
                f"TO '{path.as_posix()}' (FORMAT parquet)")


def _fixture(tmp_path):
    con = duckdb.connect()
    paths = {name: tmp_path / f"{name}.parquet" for name in ("recalls", "root_causes", "recall_drugs")}
    recalls, causes, drugs = [], [], []
    # four rule-tagged recalls in two events, two tagged by Claude, and two named by Claude
    # that have no root cause yet, so each group's candidates are known exactly
    for n, event, source, id_source in [(1, "e1", "rule", "openfda"), (2, "e1", "rule", "openfda"),
                                        (3, "e2", "rule", "openfda"), (4, "e2", "rule", "openfda"),
                                        (5, "e3", "claude", "openfda"), (6, "e4", "claude", "openfda"),
                                        (7, "e5", None, "claude"), (8, "e6", None, "claude")]:
        number = f"D-{n}"
        recalls.append({"recall_number": number, "event_id": event, "report_date": "20250101",
                        "classification": "Class II", "recalling_firm": "Firm",
                        "product_description": f"Product {n}", "reason_for_recall": f"Reason {n}"})
        causes.append({"recall_number": number, "root_cause": "CGMP" if source else None,
                       "source": source, "confidence": "high" if source == "claude" else None})
        drugs.append({"recall_number": number, "drug_key": "heparin sodium", "id_source": id_source})
    _parquet(con, paths["recalls"], recalls)
    _parquet(con, paths["root_causes"], causes)
    _parquet(con, paths["recall_drugs"], drugs)
    return con, paths


def test_sample_takes_one_recall_per_event_and_skips_the_first_audit(tmp_path):
    con, paths = _fixture(tmp_path)
    rows = sample_rows(con, paths, exclude={"D-1"}, per_group=2)
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r["recall_number"])
    assert "D-1" not in {r["recall_number"] for r in rows}
    # e1 gives D-2, since D-1 was in the first audit, and e2 gives just one of D-3 and D-4
    assert "D-2" in groups["rules"] and len(groups["rules"]) == 2
    assert len({"D-3", "D-4"} & set(groups["rules"])) == 1
    assert sorted(groups["claude_tag"]) == ["D-5", "D-6"]
    assert sorted(groups["claude_drug"]) == ["D-7", "D-8"]
    assert len({r["recall_number"] for r in rows}) == len(rows)                    # no repeats


def test_sheet_is_blind(tmp_path):
    con, paths = _fixture(tmp_path)
    rows = sample_rows(con, paths, exclude=set(), per_group=1)
    make_sheet(rows, tmp_path / "fresh.xlsx")
    labels = read_labels(tmp_path / "fresh.xlsx")
    assert len(labels) == len(rows)
    assert set(labels[0]) == {"recall_number", "report_date", "class", "firm", "product_description",
                              "reason_for_recall", "root_cause", "drug", "notes"}
    assert all(not r["root_cause"] and not r["drug"] for r in labels)   # nothing filled in for you


def test_score_by_who_tagged_and_named():
    pipeline = [
        {"recall_number": "D-1", "group": "rules", "root_cause": "CGMP", "root_cause_source": "rule",
         "confidence": "", "drug_key": "heparin sodium", "drug_source": "openfda"},
        {"recall_number": "D-2", "group": "claude_tag", "root_cause": "Sterility",
         "root_cause_source": "claude", "confidence": "high", "drug_key": "", "drug_source": ""},
        {"recall_number": "D-3", "group": "claude_drug", "root_cause": "Potency",
         "root_cause_source": "rule", "confidence": "", "drug_key": "fentanyl citrate",
         "drug_source": "claude"},
    ]
    labels = [
        {"recall_number": "D-1", "root_cause": "Impurities", "drug": "Heparin Sodium"},
        {"recall_number": "D-2", "root_cause": "Sterility", "drug": "morphine sulfate"},
        {"recall_number": "D-3", "root_cause": "Potency", "drug": "fentanyl"},
    ]
    r = score(labels, pipeline)
    assert r["causes"] == {"rule": [1, 2], "claude": [1, 1]}
    assert r["drugs"]["matching"] == [1, 1, 1]
    assert r["drugs"]["claude"] == [0, 1, 1]          # wrong exactly, right ignoring the salt
    assert r["not_named"] == 1                         # D-2: the pipeline named nothing
    assert {(m[0], m[2]) for m in r["misses"]} == {("D-1", "root cause"), ("D-2", "drug")}
