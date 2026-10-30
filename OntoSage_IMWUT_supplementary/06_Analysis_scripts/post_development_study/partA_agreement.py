#!/usr/bin/env python3
"""Part A: agreement with the second coder's 100 rows, and the agreed file (tracker F3, G14).

    python partA_agreement.py agree labels/partA/partA_codes_author.csv RETURNED_sheet_5.csv
    python partA_agreement.py finalise labels/partA/agreement/agreed_draft.csv

agree: Cohen's kappa per single-value field (F3a-F6) and mean Jaccard with per-value kappa for F1 and F2, over the
rows both coded (analysis_partA.agreement), into labels/partA/agreement/: agreement.json, disagreements.csv, and
agreed_draft.csv, which is coder 1's 400 rows with every disagreeing cell left empty.

At the meeting the coders fill each empty cell. Where they still disagree, coder 1's value stays and 'yes' goes under
'disputed' (plan 19 D7).

finalise: checks the codes against the codebook and the disputed rows against coder 1, then writes
labels/partA/partA_codes_agreed.csv (partA_results.py then reads it: HUMAN_AGREED) and settlement.json beside the
draft. Coder 1 is the first author's review of the AI's proposals for all 400 rows, so the agreed file is those codes
with the sample's disagreements settled.

The same code as the mixed questions' agreement (rq1_fresh_vs_corpus.agree / finalise), keyed by row_id.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rq1_fresh_vs_corpus as R  # noqa: E402
from study_paths import LABELS  # noqa: E402

PA = LABELS / "partA"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["agree", "finalise"])
    ap.add_argument("files", nargs="+", help="agree: CODER1 CODER2; finalise: DRAFT")
    ap.add_argument("--out", default="", help="agree: write here instead of labels/partA/agreement/ (for tests)")
    ap.add_argument("--to", default="", help="finalise: write here instead of labels/partA/ (for tests)")
    a = ap.parse_args()
    if a.mode == "agree":
        if len(a.files) < 2:
            ap.error("agree needs two coder sheets")
        return R.agree(a.files[0], a.files[1], out=Path(a.out) if a.out else PA / "agreement", id_col="row_id")
    return R.finalise(a.files[0], to=Path(a.to) if a.to else PA / "partA_codes_agreed.csv", id_col="row_id",
                      material="partA")


if __name__ == "__main__":
    raise SystemExit(main())
