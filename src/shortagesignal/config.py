"""Where things live on disk. Every module imports paths from here."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The scheduled pipeline can point this somewhere else, like a checkout of the data branch.
DATA_DIR = Path(os.getenv("SHORTAGESIGNAL_DATA_DIR", str(ROOT / "data")))

RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "shortagesignal.duckdb"
STATE_PATH = DATA_DIR / "state.json"
RECALLS_PATH = DATA_DIR / "recalls.parquet"
RECALL_VERSIONS_PATH = DATA_DIR / "recall_versions.parquet"
SNAPSHOTS_PATH = DATA_DIR / "shortage_snapshots.parquet"
CURRENT_SHORTAGES_PATH = DATA_DIR / "shortages_current.parquet"
HISTORY_PATH = DATA_DIR / "shortage_history.parquet"
NDC_PATH = DATA_DIR / "ndc.parquet"
RUN_LOG_PATH = DATA_DIR / "run_log.csv"
