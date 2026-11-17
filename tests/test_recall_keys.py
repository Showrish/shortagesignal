from datetime import date, datetime

import duckdb

from shortagesignal.ingest import merge_recalls, recall_key


def _recall(number, event, product):
    return {"recall_number": number, "event_id": event, "product_description": product,
            "report_date": "20261101", "recalling_firm": "A Firm"}


def test_recall_key_keeps_real_numbers_and_gives_placeholders_their_own():
    assert recall_key(_recall("D-0123-2026", "e1", "Heparin")) == "D-0123-2026"
    a, b = recall_key(_recall("N/A", "e1", "Heparin")), recall_key(_recall("N/A", "e2", "Saline"))
    assert a.startswith("NA-") and b.startswith("NA-") and a != b      # no more sharing one key
    assert recall_key(_recall(" n/a ", "e1", "Heparin")) == a            # the same recall, the same key
    assert recall_key(_recall(None, "e1", "Heparin")) == a               # no number at all, too
    assert recall_key(_recall("", None, None)) is None                   # nothing to tell it apart by


def test_merge_brings_back_a_recall_an_old_placeholder_overwrote(tmp_path):
    con = duckdb.connect()
    latest, history = tmp_path / "recalls.parquet", tmp_path / "recall_versions.parquet"
    stamps = "'h' AS _content_hash, DATE '2026-11-01' AS _first_seen, TIMESTAMP '2026-11-01 12:00:00' AS _pulled_at"
    # before the fix: two recalls came in as N/A, so the latest table kept only the second one,
    # while the history kept both
    con.execute(f"COPY (SELECT 'N/A' AS recall_number, 'e2' AS event_id, 'Saline' AS product_description, "
                f"{stamps}) TO '{latest.as_posix()}' (FORMAT PARQUET)")
    con.execute(f"COPY (SELECT * FROM (VALUES ('N/A', 'e1', 'Heparin'), ('N/A', 'e2', 'Saline')) "
                f"AS v(recall_number, event_id, product_description), (SELECT {stamps}) AS s) "
                f"TO '{history.as_posix()}' (FORMAT PARQUET)")

    # today's pull has a normal recall, and the first N/A one again
    batch = [_recall("D-0009-2026", "e3", "Lidocaine"), _recall("N/A", "e1", "Heparin")]
    merge_recalls(con, batch, latest, history, date(2026, 11, 16), datetime(2026, 11, 16, 12), tmp_path)

    keys = {k for (k,) in con.execute(f"SELECT recall_number FROM read_parquet('{latest.as_posix()}')").fetchall()}
    # every recall is there once: the normal one, the N/A one pulled again under the same key
    # the stored row was given, and the one that had been overwritten, back from the history
    assert keys == {"D-0009-2026", recall_key(_recall("N/A", "e1", "Heparin")),
                    recall_key(_recall("N/A", "e2", "Saline"))}
