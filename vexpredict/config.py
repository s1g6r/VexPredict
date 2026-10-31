"""Paths and token loading shared by every module."""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VEXPREDICT_DATA", ROOT / "data"))
REPORTS_DIR = ROOT / "reports"

API_BASE = os.environ.get("VEX_API_BASE", "https://events.vex.com/api/v2")
V5RC_PROGRAM_ID = 1
HIGH_SCHOOL = "High School"


def season_dir(slug: str) -> Path:
    return DATA_DIR / "raw" / slug


def load_token() -> str:
    """Return the VEX Events API token.

    Looks at the VEX_TOKEN environment variable first, then a .env file in the
    project root. Tolerates `VEX_TOKEN = abc`, quotes, and stray whitespace.
    """
    tok = os.environ.get("VEX_TOKEN")
    if tok:
        return tok.strip().strip("'\"")
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?VEX_TOKEN\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip("'\"")
    raise SystemExit(
        "No VEX API token found. Put `VEX_TOKEN=...` in a .env file in the "
        "project folder (same format as VexCompare) or export VEX_TOKEN."
    )


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
