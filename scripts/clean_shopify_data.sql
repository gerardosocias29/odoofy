-- SQL script to clean Shopify data from Odoo database
-- Run these commands in your PostgreSQL client

-- 1. Delete Shopify product variants
DELETE FROM product_product WHERE default_code LIKE 'SHOPIFY_%';

-- 2. Delete Shopify product templates  
DELETE FROM product_template WHERE default_code LIKE 'SHOPIFY_%';

-- 3. Delete Shopify orders
DELETE FROM sale_order WHERE client_order_ref LIKE 'SHOPIFY_%';

-- 4. Delete sync records
DELETE FROM shopify_sync;

-- 5. Reset Shopify configuration parameters
UPDATE ir_config_parameter SET value = '' WHERE key = 'shopify.last_updated_at';
UPDATE ir_config_parameter SET value = '' WHERE key = 'shopify.orders_last_updated_at';
UPDATE ir_config_parameter SET value = '' WHERE key = 'shopify.total_products_count';
UPDATE ir_config_parameter SET value = '' WHERE key = 'shopify.total_orders_count';
UPDATE ir_config_parameter SET value = '' WHERE key = 'shopify.last_odoo_to_shopify_sync';

-- 6. Clean up Shopify attachments (optional)
DELETE FROM ir_attachment WHERE name LIKE '%shopify%' OR name LIKE '%SHOPIFY%';

-- 7. Reset sequences (optional - if you want clean IDs)
-- SELECT setval('product_template_id_seq', (SELECT MAX(id) FROM product_template));
-- SELECT setval('product_product_id_seq', (SELECT MAX(id) FROM product_product));
-- SELECT setval('sale_order_id_seq', (SELECT MAX(id) FROM sale_order));

COMMIT;
