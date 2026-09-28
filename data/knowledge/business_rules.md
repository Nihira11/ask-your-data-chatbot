# Metric definitions for the sample

Currency: GBP (pounds sterling). These are historical transactions from 2010–2011.
Revenue, an explicit project definition: SUM(quantity * unit_price) across order_items
with unit_price >= 0. Signed negative quantities reduce revenue, including cancellation
credits. Zero prices are retained. Negative prices are excluded as invalid for this metric.
This is net invoiced value, not audited accounting revenue or profit. VAT, costs, and
separate discounts are unavailable; never invent them.

Invoice count includes cancellation invoices unless explicitly filtered. Sales invoice
count means is_cancellation = 0. These measures are not interchangeable.
A cancellation is identified by the C prefix on the invoice ID, as documented by UCI.
Do not automatically interpret every negative quantity without that prefix as a refund.
The sample's credits may refer to original sales outside the sample.

Use order_date for time filters; both December periods are partial. A monthly breakdown
is a breakdown of the selected invoices, not a representative retailer trend.
Missing customers are retained in revenue. Blank descriptions/country are NULL. Original
source duplicate lines are retained. Round monetary totals to two decimals only after
summing; SQLite REAL is adequate for this demo but is not a financial ledger.
For “best” or “performance”, ask which metric and period. No rows is a valid result;
SUM over no matching rows is NULL unless SQL explicitly uses COALESCE.
