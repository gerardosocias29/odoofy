# exec(open('addons/odoofy/scripts/clean_sales_and_invoices.py').read())

print("💣 Executing raw SQL deletes to wipe Sales Orders and Invoices...")

cr = env.cr

# === Step 0: Delete reconciliation records
cr.execute("""
    DELETE FROM account_partial_reconcile 
    WHERE debit_move_id IN (
        SELECT id FROM account_move_line WHERE move_id IN (
            SELECT id FROM account_move WHERE move_type = 'out_invoice'
        )
    ) OR credit_move_id IN (
        SELECT id FROM account_move_line WHERE move_id IN (
            SELECT id FROM account_move WHERE move_type = 'out_invoice'
        )
    )
""")

# === Step 1: Delete account move lines
cr.execute("DELETE FROM account_move_line WHERE move_id IN (SELECT id FROM account_move WHERE move_type = 'out_invoice')")

# === Step 2: Delete account moves (invoices)
cr.execute("DELETE FROM account_move WHERE move_type = 'out_invoice'")

# === Step 3: Delete sale order lines
cr.execute("DELETE FROM sale_order_line WHERE order_id IN (SELECT id FROM sale_order)")

# === Step 4: Delete sale orders
cr.execute("DELETE FROM sale_order")

# === Step 5: Delete stock moves and pickings related to sales
cr.execute("DELETE FROM stock_move WHERE picking_id IN (SELECT id FROM stock_picking WHERE origin ILIKE 'SO%')")
cr.execute("DELETE FROM stock_picking WHERE origin ILIKE 'SO%'")

# === Optional: Clean mail.message chatter linked to those models
cr.execute("DELETE FROM mail_message WHERE model IN ('sale.order', 'account.move')")

# Commit changes
cr.commit()

print("✅ All sales orders, invoices, reconciliations, related lines, stock moves, and chatter deleted via raw SQL.")
