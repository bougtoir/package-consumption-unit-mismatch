# Dry-rice and packaging trade-off feasibility

The evidence tables document Japanese retail listings, primary packaging specifications, and household rice inventory and loss evidence. Listed options establish availability in the sources examined. Actual primary packaging mass for the selected food products and the household exit share of uncooked rice by package size remain unidentified.

Run from the project root with Python 3.10 or later.

```sh
python -m pip install -e '.[dev]'
MPLBACKEND=Agg python analysis/run_resource_tradeoff.py
python -m pytest -q
```

`RESOURCE_TRADEOFF_RESULTS.csv` compares `ref_offered_kg` and `alt_offered_kg` for each configured household type with no empirical weights. The model assigns the largest available bag at or below the household's handling threshold, or the smallest bag if none qualify. Adaptation and physical exit are disabled for the negative control. Each pair uses the same consumption event stream and empty opening stock. `consumed_kg`, `purchased_kg`, `physical_discard_kg` and `purchases` are annualized. `ending_inventory_kg` is a stock at the end of the entire simulation.

The packaging proxy is the number of bags times the listed HEIKO LDPE bag mass. The 2 kg specification is for a discontinued item. The 5 kg and 10 kg bands span two catalog entries for the corresponding specification. The paired Monte Carlo intervals describe simulation error at the catalog endpoints. Retail bag mass is blank because actual bag weights were unavailable.

For the analytic comparison and plots, hold dry-rice consumption fixed and set the net change in stock to zero. If the fraction of purchases exiting as waste is `q`, packaging per kg of consumption is `(bag mass / bag capacity) / (1 - q)`. The table shows the larger bag's waste share at packaging parity given zero waste with the smaller bag. Positive exit shares are mathematical thresholds. The public sources do not establish an empirical exit range, so the market packaging and food exit trade-off remains unidentified.
