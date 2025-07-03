print("💣 Executing raw SQL deletes to wipe Purchase Orders and Lines...")
cr = env.cr

cr.execute("DELETE FROM purchase_order_line")
cr.execute("DELETE FROM purchase_order")

print("✅ All purchase orders and lines deleted via raw SQL.")