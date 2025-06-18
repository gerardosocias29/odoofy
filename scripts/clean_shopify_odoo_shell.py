#!/usr/bin/env python3
"""
Odoo shell script to clean Shopify data
Run with: python3 odoo-bin shell -c odoo.conf --shell-interface ipython
Then execute: exec(open('addons/odoofy/scripts/clean_shopify_odoo_shell.py').read())
"""

print("🧹 Starting Shopify data cleanup via Odoo shell...")

# 1. Identify Shopify products and variants
shopify_products = env['product.template'].search([('default_code', 'like', 'SHOPIFY_%')])
shopify_variants = env['product.product'].search([('default_code', 'like', 'SHOPIFY_%')])

# 2. Delete related sale order lines
print("Deleting sale order lines for Shopify products...")
order_lines = env['sale.order.line'].search([('product_id', 'in', shopify_variants.ids)])
order_line_count = len(order_lines)
order_lines.sudo().unlink()
print(f"   ✅ Deleted {order_line_count} sale order lines")

# 3. Delete related stock quants
print("Deleting related stock quants for Shopify products...")
stock_quants = env['stock.quant'].search([('product_id', 'in', shopify_variants.ids)])
quant_count = len(stock_quants)
stock_quants.sudo().unlink()
print(f"   ✅ Deleted {quant_count} stock quants")

# 4. Delete purchase requisition lines for Shopify products
print("Deleting purchase requisition lines for Shopify products...")
pr_lines = env['purchase.requisition.line'].search([('product_id', 'in', shopify_variants.ids)])
pr_line_count = len(pr_lines)
pr_lines.sudo().unlink()
print(f"   ✅ Deleted {pr_line_count} purchase requisition lines")

# Delete purchase order lines for Shopify products
print("Deleting purchase order lines for Shopify products...")
po_lines = env['purchase.order.line'].search([('product_id', 'in', shopify_variants.ids)])
po_line_count = len(po_lines)
po_lines.sudo().unlink()
print(f"   ✅ Deleted {po_line_count} purchase order lines")

# Reset parent journal entries to draft before deleting lines (DANGEROUS: test/dev only!)
print("Resetting parent journal entries to draft...")
aml_lines = env['account.move.line'].search([('product_id', 'in', shopify_variants.ids)])
parent_moves = aml_lines.mapped('move_id').filtered(lambda m: m.state == 'posted')
move_count = len(parent_moves)
if move_count:
    parent_moves.sudo().button_draft()
print(f"   ✅ Reset {move_count} journal entries to draft")

# Now delete account move lines
print("Deleting account move lines for Shopify products...")
aml_line_count = len(aml_lines)
aml_lines.sudo().unlink()
print(f"   ✅ Deleted {aml_line_count} account move lines")

# 5. Cancel and delete Shopify orders
print("Deleting Shopify orders...")
shopify_orders = env['sale.order'].search([('client_order_ref', 'like', 'SHOPIFY_%')])
order_count = len(shopify_orders)
for order in shopify_orders:
    if order.state not in ('draft', 'cancel'):
        order.sudo().action_cancel()
orders_to_delete = env['sale.order'].search([
    ('client_order_ref', 'like', 'SHOPIFY_%'),
    ('state', 'in', ['draft', 'cancel'])
])
orders_to_delete.sudo().unlink()
print(f"   ✅ Deleted {order_count} orders")

# 6. Delete Shopify product variants and templates
print("Deleting Shopify variants...")
variant_count = len(shopify_variants)
shopify_variants.sudo().unlink()
print(f"   ✅ Deleted {variant_count} product variants")

print("Deleting Shopify products...")
product_count = len(shopify_products)
shopify_products.sudo().unlink()
print(f"   ✅ Deleted {product_count} product templates")

# 7. Delete sync records
print("Deleting sync records...")
sync_records = env['shopify.sync'].search([])
sync_count = len(sync_records)
sync_records.sudo().unlink()
print(f"   ✅ Deleted {sync_count} sync records")

# 8. Reset configuration parameters
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

# 9. Clean up Shopify attachments
print("Cleaning up attachments...")
shopify_attachments = env['ir.attachment'].search([
    '|', ('name', 'ilike', 'shopify'), ('name', 'ilike', 'SHOPIFY')
])
attachment_count = len(shopify_attachments)
shopify_attachments.sudo().unlink()
print(f"   ✅ Deleted {attachment_count} attachments")

# Commit changes
env.cr.commit()

print("\n🎉 Shopify data cleanup completed successfully!")
print(f"Summary:")
print(f"  - Products deleted: {product_count}")
print(f"  - Variants deleted: {variant_count}")
print(f"  - Orders deleted: {order_count}")
print(f"  - Sale order lines deleted: {order_line_count}")
print(f"  - Sync records deleted: {sync_count}")
print(f"  - Attachments deleted: {attachment_count}")
print(f"  - Config parameters reset: {len(params_to_reset)}")
print(f"  - Stock quants deleted: {quant_count}")
print(f"  - Purchase requisition lines deleted: {pr_line_count}")
print(f"  - Purchase order lines deleted: {po_line_count}")
print(f"  - Account move lines deleted: {aml_line_count}")
print("\n✨ Ready for fresh Shopify sync with new timestamp-based system!")
