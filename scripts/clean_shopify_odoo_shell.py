#!/usr/bin/env python3
"""
Odoo shell script to clean Shopify data
Run with: python3 odoo-bin shell -c odoo.conf --shell-interface ipython
Then execute: exec(open('scripts/clean_shopify_odoo_shell.py').read())
"""

print("🧹 Starting Shopify data cleanup via Odoo shell...")

# 1. Delete related stock quants for Shopify products
print("Deleting related stock quants for Shopify products...")
shopify_products = env['product.template'].search([('default_code', 'like', 'SHOPIFY_%')])
shopify_variants = env['product.product'].search([('default_code', 'like', 'SHOPIFY_%')])

# Delete stock quants
stock_quants = env['stock.quant'].search([('product_id', 'in', shopify_variants.ids)])
quant_count = len(stock_quants)
stock_quants.sudo().unlink()
print(f"   ✅ Deleted {quant_count} stock quants")

# Now delete products as before
print("Deleting Shopify products...")
product_count = len(shopify_products)
shopify_products.sudo().unlink()
print(f"   ✅ Deleted {product_count} product templates")

print("Deleting Shopify variants...")
variant_count = len(shopify_variants)
shopify_variants.sudo().unlink()
print(f"   ✅ Deleted {variant_count} product variants")

# 2. Delete Shopify orders
print("Deleting Shopify orders...")
shopify_orders = env['sale.order'].search([('client_order_ref', 'like', 'SHOPIFY_%')])
order_count = len(shopify_orders)

# Cancel orders that are not in 'draft' or 'cancel'
for order in shopify_orders:
    if order.state not in ('draft', 'cancel'):
        order.sudo().action_cancel()

# Re-search for orders now in 'draft' or 'cancel' state
orders_to_delete = env['sale.order'].search([
    ('client_order_ref', 'like', 'SHOPIFY_%'),
    ('state', 'in', ['draft', 'cancel'])
])
orders_to_delete.sudo().unlink()
print(f"   ✅ Deleted {order_count} orders")

# 3. Delete sync records
print("Deleting sync records...")
sync_records = env['shopify.sync'].search([])
sync_count = len(sync_records)
sync_records.unlink()
print(f"   ✅ Deleted {sync_count} sync records")

# 4. Reset configuration parameters
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

# 5. Clean up Shopify attachments
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
print(f"  - Stock quants deleted: {quant_count}")
print("\n✨ Ready for fresh Shopify sync with new timestamp-based system!")
