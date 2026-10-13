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
NDC_DIRECTORY_PATH = DATA_DIR / "ndc_directory.parquet"
RECALL_IDS_PATH = DATA_DIR / "recall_ids.parquet"
SHORTAGE_IDS_PATH = DATA_DIR / "shortage_ids.parquet"
RECALL_DRUGS_PATH = DATA_DIR / "recall_drugs.parquet"
SHORTAGE_DRUGS_PATH = DATA_DIR / "shortage_drugs.parquet"
LINKS_PATH = DATA_DIR / "recall_shortage_links.parquet"
UNMATCHED_PATH = DATA_DIR / "unmatched_recalls.parquet"
ROOT_CAUSES_PATH = DATA_DIR / "recall_root_causes.parquet"
CLAUDE_TAGS_PATH = DATA_DIR / "claude_tags.parquet"
TAG_REVIEW_PATH = DATA_DIR / "tag_review.csv"
RUN_LOG_PATH = DATA_DIR / "run_log.csv"
CHECK_LOG_PATH = DATA_DIR / "check_log.csv"
