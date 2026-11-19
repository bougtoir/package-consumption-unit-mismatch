# FINAL HANDOFF — PCUM → Computers & Industrial Engineering (final revision)

Date: 2026-10-16 (rev. 2). Branch: `devin/1792122050-pcum-caie-final`
(off master `60d110f61`, post-merge of PR #686).

## Verdict: GO

Final CAIE package complete in `submission/CAIE/` +
`CAIE_submission_FINAL.zip`. No scientific content changed; no new
analyses; `manuscript_values.csv` and all frozen values byte-identical.

## What changed since PR #686 (the first CAIE package)

- **Figure/table density fixed.** Main text now 5 figures + 5 tables
  (was 9 + 14). Moved to `supplement.docx`: Tables S1–S9 (households,
  regimes, factorial, consumption, dense thresholds, grid, minimax,
  fill precision, cross-product) and Figures S1–S4 (lattice, pareto,
  grid, manufacturing). Nothing deleted; renumbering is automatic by
  first-citation order in `analysis/build_manuscript.py`.
- **Cover letter rewritten.** Literature-specific novelty paragraph
  (named prior work on both sides of the gap), three concrete
  contributions, calibrated claims — no sweeping priority statement, no
  Japan-market optimality claim.
- **Title page** declares main + supplementary counts and
  `supplement.docx`.
- **Data availability verified live**: public repo
  bougtoir/package-consumption-unit-mismatch exists, contains code +
  generated outputs only; restricted snapshots correctly absent;
  archival DOI remains a stated plan (not a claimed artifact).
- Audits extended for S-numbering + supplement presence/blinding;
  `submission/CAIE/` ships supplement.docx.

## Verified state

14/14 tests; ruff clean; 13 audit suites pass (reference 28/28,
citation entailment 23/23, figure_table 23/23 incl. supplement,
compliance 10/10, anonymity 37/37). Rebuild:

```
PYTHONPATH=src .venv/bin/python analysis/build_manuscript.py   # +supplement.docx
PYTHONPATH=src .venv/bin/python analysis/run_audits.py
PYTHONPATH=src .venv/bin/python analysis/build_reports.py
PYTHONPATH=src .venv/bin/python analysis/build_submission.py
```

`make reproduce` only if outputs must be regenerated (≈15 min).

## Frozen values (unchanged)

terminal residual 393.9 g; cell discard 2.779 kg; thresholds 470.9/36.8
JPY; 1-vs-2 diff 290.9 (287.6–294.2); minimax 5|10 @429.1; margin 61.8 g;
phase shares 38.9/49.9/11.2%.

## Standing constraints

- Scenario values remain calibration examples, never market
  recommendations or "Japan-optimal".
- Editorial Manager metadata still user-unconfirmed — left unfilled.
- `submission/` already inside pcum-public-sync EXCLUDE_MAP.
- If CAIE rejects: reuse this branch's APA machinery + supplement
  mechanism for the next Elsevier retarget.
