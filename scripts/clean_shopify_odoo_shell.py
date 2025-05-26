#!/usr/bin/env python3
"""
Odoo shell script to clean Shopify data
Run with: python3 odoo-bin shell -c odoo.conf --shell-interface ipython
Then execute: exec(open('scripts/clean_shopify_odoo_shell.py').read())
"""

print("🧹 Starting Shopify data cleanup via Odoo shell...")

# 1. Delete Shopify products
print("Deleting Shopify products...")
shopify_products = env['product.template'].search([('default_code', 'like', 'SHOPIFY_%')])
product_count = len(shopify_products)
shopify_products.unlink()
print(f"   ✅ Deleted {product_count} product templates")

# 2. Delete Shopify product variants (if any remain)
print("Deleting Shopify variants...")
shopify_variants = env['product.product'].search([('default_code', 'like', 'SHOPIFY_%')])
variant_count = len(shopify_variants)
shopify_variants.unlink()
print(f"   ✅ Deleted {variant_count} product variants")

# 3. Delete Shopify orders
print("Deleting Shopify orders...")
shopify_orders = env['sale.order'].search([('client_order_ref', 'like', 'SHOPIFY_%')])
order_count = len(shopify_orders)
shopify_orders.unlink()
print(f"   ✅ Deleted {order_count} orders")

# 4. Delete sync records
print("Deleting sync records...")
sync_records = env['shopify.sync'].search([])
sync_count = len(sync_records)
sync_records.unlink()
print(f"   ✅ Deleted {sync_count} sync records")

# 5. Reset configuration parameters
print("Resetting configuration parameters...")
config_param = env['ir.config_parameter'].sudo()
params_to_reset = [
    'shopify.last_updated_at',
    'shopify.orders_last_updated_at', 
    'shopify.total_products_count',
    'shopify.total_orders_count',
    'shopify.last_odoo_to_shopify_sync'
]

for param in params_to_reset:
    config_param.set_param(param, '')

print(f"   ✅ Reset {len(params_to_reset)} configuration parameters")

# 6. Clean up Shopify attachments
print("Cleaning up attachments...")
shopify_attachments = env['ir.attachment'].search([
    '|', ('name', 'ilike', 'shopify'), ('name', 'ilike', 'SHOPIFY')
])
attachment_count = len(shopify_attachments)
shopify_attachments.unlink()
print(f"   ✅ Deleted {attachment_count} attachments")

# Commit changes
env.cr.commit()

print("\n🎉 Shopify data cleanup completed successfully!")
print(f"Summary:")
print(f"  - Products deleted: {product_count}")
print(f"  - Variants deleted: {variant_count}")
print(f"  - Orders deleted: {order_count}")
print(f"  - Sync records deleted: {sync_count}")
print(f"  - Attachments deleted: {attachment_count}")
print(f"  - Config parameters reset: {len(params_to_reset)}")
print("\n✨ Ready for fresh Shopify sync with new timestamp-based system!")
