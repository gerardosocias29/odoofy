# exec(open('addons/odoofy/scripts/clean_purchase_orders.py').read())
print("💣 Executing raw SQL deletes to wipe Purchase Orders and Lines...")
cr = env.cr

# Delete purchase order lines first (to avoid FK constraint errors)
cr.execute("DELETE FROM purchase_order_line")

# Delete purchase orders
cr.execute("DELETE FROM purchase_order")

# Optionally, clean up ir.model.data references (removes menu links, etc.)
cr.execute("DELETE FROM ir_model_data WHERE model = 'purchase.order' OR model = 'purchase.order.line'")

cr.commit()

print("✅ All purchase orders and lines deleted via raw SQL.")