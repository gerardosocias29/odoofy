# exec(open('addons/odoofy/scripts/rename_sales_orders.py').read())

print("✏️ Renaming Sales Orders: prefix S → EPO-")

cr = env.cr

# Count matching records
cr.execute("""
    SELECT COUNT(*) FROM sale_order
    WHERE name LIKE 'S%' AND name NOT LIKE 'EPO-%'
""")
count = cr.fetchone()[0]
print(f"🔍 Found {count} Sales Orders to rename...")

# Correct update
cr.execute("""
    UPDATE sale_order
    SET name = regexp_replace(name::text, '^S', 'EPO-')
    WHERE name LIKE 'S%' AND name NOT LIKE 'EPO-%'
""")

cr.execute("""
    UPDATE stock_picking
    SET origin = regexp_replace(origin::text, '^S', 'EPO-')
    WHERE origin LIKE 'S%' AND origin NOT LIKE 'EPO-%'
""")

cr.commit()

print("✅ Sales Orders renamed successfully.")
