# Package–Consumption Unit Mismatch (PCUM)

Reproducible production-economics study of package-capacity choice when
consumption occurs in stochastic discrete units. The project separates:

- terminal residual: a one-package diagnostic;
- carry-over inventory: stock retained across purchases;
- discard: physical loss caused by an explicit spoilage mechanism;
- adaptation: changes to the immediate use quantity, with deferred demand carried forward;
- producer assortment: one-, two-, and three-SKU portfolios with complexity
  charges.

Rice is the principal calibration and application case. Numerical results are
scenario results unless an input is explicitly linked to a frozen public source
in `provenance/acquisition_ledger.csv`.

The household classes are design scenarios, not estimates of latent population
segments. Their weights preserve the census split between one-person and other
households, then divide each aggregate across low and average-consumption
scenarios. National rice supply anchors annual quantities but does not identify
event-size probabilities, adaptation, spoilage, or household discard.

## Reproduce

Numerical results, figures, and tables:

```bash
make setup
make reproduce
make test
```

`make reproduce` regenerates processed inputs from `config/default.yaml`, runs
the simulations and portfolio optimization, and writes `output/`, `figures/`,
and `tables/`. The public mirror contains only this reproduction code.

Complete research build:

```bash
make setup
make all
make test
```

`make all` regenerates processed inputs, simulation results, replication-level
paired portfolio comparisons, figures, tables, manuscript value files, DOCX
outputs, editable figure/table files, audits, and submission archives. With the
complete local source snapshots it creates all four archives; a public checkout
without restricted snapshots creates the redistributable archive only.

The private complete bundle retains every frozen source snapshot. The
redistributable bundle contains only Crossref metadata among third-party raw
files and includes `PUBLIC_DISTRIBUTION.txt`; in that mode, source checks record
policy-excluded snapshots as unavailable rather than silently substituting
them. Editorial and blinded-review archives are separate so identified files
cannot be mixed into the reviewer package.

## Important interpretation

Modulo residual is not waste. Under full carry-over and no spoilage, package
quantity mismatch produces no physical discard in the model. Package design
matters only through explicitly modelled storage, freshness, handling,
packaging, purchase-frequency, price, adaptation, spoilage, and SKU-complexity
channels.

## Structure

- `config/`: centralized assumptions and random seed
- `data/raw/`: immutable snapshots from public sources
- `data/processed/`: code-generated model inputs
- `src/pcum/`: inventory simulation and portfolio optimization
- `analysis/`: executable pipeline
- `figures/`, `tables/`: generated publication assets
- `manuscript/`: source and generated documents
- `provenance/`: source and acquisition records
- `reports/`: QC, traceability, and reviewer audits

## License

Code is released under the MIT License. Third-party source snapshots retain
their original terms; see the acquisition ledger and redistribution policy.
