# Bundled UCI Online Retail sample

Source: Daqing Chen (2015), **Online Retail**, UCI Machine Learning Repository.
DOI: https://doi.org/10.24432/C5BW33
Dataset: https://archive.ics.uci.edu/dataset/352/online-retail
Licence: Creative Commons Attribution 4.0 International (CC BY 4.0):
https://creativecommons.org/licenses/by/4.0/

The source describes transactions at a UK online retailer from December 2010 to
December 2011. Unit prices are in GBP. Invoice IDs beginning C indicate cancellations.

## Adaptations made for this project

`online_retail_sample.csv` keeps the first 25 non-cancellation invoices and first
5 cancellation invoices in each calendar month in original workbook order. All
lines belonging to selected invoices are retained. This is a deliberate demo
sample, **not a random or representative sample**. Never treat its totals or monthly
changes as totals or growth rates of the whole business.

Headers are renamed to snake_case, dates to ISO timestamps, and numeric identifier
cells to text. Blank cells are preserved as empty CSV fields. Source duplicates remain.
The importer splits these rows into orders, order_items, products and customers;
product names use the first observed description. Country remains on the invoice.
Invoice dates use the earliest line timestamp; original timestamps remain on every
order item. Invoice 542806 has lines recorded at 11:19 and 11:20 on 1 February 2011.
No costs, categories, discounts, or customer contact details are invented.

`manifest.json` records the selected row count, dates, source attribution, selection
rule, and checksums for both the sample CSV and original downloaded ZIP.

To reproduce, download the original ZIP from UCI, install `openpyxl`, then run:

```bash
python scripts/prepare_sample.py /path/to/online+retail.zip
```

Downloading/reprocessing the original workbook is not required to run the app.
The data licence applies to the attributed dataset; no repository software licence
has been added.
