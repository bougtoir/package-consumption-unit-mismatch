# FINAL HANDOFF — PCUM → Computers & Industrial Engineering

Date: 2026-10-16. Branch: `devin/1792109865-pcum-caie` (off master
`a5de22f35`; baseline recorded `a42da1c48`).

## State

All six gates PASS. The manuscript is retargeted to *Computers &
Industrial Engineering* (subscription route — no APC; verified against
the Elsevier Guide for Authors 2026-10-16). Deliverables live in
`submission/CAIE/` including `CAIE_submission_FINAL.zip`. Gate reports
live in `reports/GATE0..GATE6*`, `GATE_STATUS.md`, `DECISION_LOG.md`,
`CLOSEST_PRIOR_STUDIES.csv`, `CITATION_ECOLOGY.md`.

## What changed since the IJPE package

- Title/abstract/§1/§4 reframed to the CAIE decision-support
  contribution: stochastic household carry-over simulation + exhaustive
  SKU-portfolio enumeration + global SKU-inclusion break-even rule
  (non-nested optima).
- Prop 1 → Lemma 1 (zero-discard boundary); Prop 2 → SKU-inclusion rule.
- Citations converted Vancouver → APA 7th; reference list = 28
  alphabetical entries (22 prior + 6 new verified: Brinker & Gündüz 2016,
  Gámez Albán 2015, Kandemir 2020, Wan Dresner & Evers 2014, Wensing
  2018, Zhao 2023 CAIE).
- Fonts TNR 12 pt body / 10 pt captions; double-anonymized package kept.
- CAIE cover letter (first person, no prior-journal mention, dated
  16 Oct 2026); scope-fit report = `reports/CAIE_SCOPE_FIT_FINAL.md`.
- `analysis/run_audits.py` reference/entailment audits rewritten for APA;
  `build_submission.py` emits `submission/CAIE/`.
- Submission zip rebuilt; `submission/IJPE/` retained untouched.

## Verified state

`make reproduce` → build_manuscript → audits → reports → package all
clean 2026-10-16; 14/14 tests; ruff clean; all 13 audits pass;
`manuscript_values.csv` byte-identical to freeze (no numeric drift).

## Frozen values (do not recompute/hardcode)

max terminal residual 393.9 g; max cell discard 2.779 kg/hh-yr; coarse
portfolios 9 / 5|10 / 5|9|10 kg; thresholds 470.9 & 36.8 JPY; 1-vs-2 diff
290.9 (287.6–294.2); dense grid 9 / 5.25|10 / 5.25|8|10 (shares
38.9/49.9/11.2%, modal 33.0%); benchmark regret 180.0; minimax 5|10
@429.1; safety margin 61.8 g.

## Rebuild

```
make setup            # only if .venv missing
make reproduce        # data + analysis + figures + tables
PYTHONPATH=src .venv/bin/python analysis/build_manuscript.py
PYTHONPATH=src .venv/bin/python analysis/run_audits.py
PYTHONPATH=src .venv/bin/python analysis/build_reports.py
PYTHONPATH=src .venv/bin/python analysis/build_submission.py
make test
```

Never edit docx directly — edit `analysis/build_manuscript.py`.

## Constraints for the next session

- Scenario values are calibration examples; never call them empirical
  estimates, market recommendations, or "Japan-optimal".
- No new references without DOI/URL verification (Crossref).
- `submission/CAIE/` is inside the already-excluded `submission` tree of
  EXCLUDE_MAP for `devin/1791334316-pcum-public-sync`; verify before
  adding any new excluded path (exact-match entries only).
- Editorial Manager upload metadata (title-page fields, author details)
  was not user-confirmed — leave unfilled.
- If CAIE rejects: reassess rather than auto-downgrade; keep this
  branch's APA reference system for any Elsevier retarget.
