"""Compatibility entrypoint for the active board-library verifier.

The former root-level NEEQ library is archived. Verification now follows the
same board-owned source and projection contract as the live application and
checks the active ChiNext library only.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import paths as workspace_paths

KNOWLEDGE = workspace_paths.knowledge_of(ROOT)

from scripts.verify_board_libraries import verify


def main():
    reports = verify(KNOWLEDGE)
    result = {
        "status": "passed" if reports and all(r["structural_status"] == "passed" for r in reports.values()) else "failed",
        "board_scope": sorted(reports),
        "reports": reports,
        "legal_correctness_verified": False,
        "human_acceptance": False,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
