# UCI Online Retail sample v1

This is a small, non-random subset of real transactions from UCI Online Retail.
All answers describe this subset; it is not suitable for estimating full-retailer totals or growth.
The sample selects the first 25 ordinary and first 5 cancellation invoices in each
calendar month in source workbook order, retaining all their lines. See sample/manifest.json.

- customers: one row per non-missing customer_id. IDs are text. No customer names or contacts.
- products: one row per product_id (original StockCode); name is the first observed description, possibly NULL. Names can vary in the source. Do not join on names.
- orders: one row per order_id (original InvoiceNo). customer_id can be NULL; order_date is the earliest line timestamp for that invoice, as ISO timestamp text. country is the country recorded for that invoice. is_cancellation is 1 for invoice IDs starting with C, otherwise 0.
- order_items: one row per source line, including duplicate lines. line_id is a generated unique key. order_id and product_id reference their parent tables; quantity is signed integer; unit_price is a GBP numeric value. invoice_date preserves the original line timestamp, which can vary within an invoice.

Joins: orders.order_id = order_items.order_id; products.product_id = order_items.product_id;
customers.customer_id = orders.customer_id. Use LEFT JOIN for customer coverage so missing
customer IDs do not remove sales. Count DISTINCT order_id after joining lines when counting invoices.
No product categories, customer cities, costs, tax rates, or discount columns are available.
