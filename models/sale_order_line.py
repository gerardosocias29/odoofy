# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from collections import defaultdict

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _get_best_seller(self):
        """
        Finds the best seller for the product on the sales order line.
        The best seller is determined by the lowest price for a given quantity.
        - It filters vendors who can supply the required quantity (min_qty).
        - Among those, it selects the one with the lowest price.
        """
        self.ensure_one()
        product = self.product_id
        
        # Filter sellers that meet the minimum quantity requirement
        eligible_sellers = product.seller_ids.filtered(
            lambda s: s.min_qty <= self.product_uom_qty
        )

        if not eligible_sellers:
            raise UserError(_(
                "No vendor found for product '%s' that can supply the required quantity of %s. "
                "Please check vendor pricelists and minimum order quantities in the 'Purchase' tab of the product."
            ) % (product.name, self.product_uom_qty))

        # Sort the eligible sellers by price to find the best one
        best_seller = sorted(eligible_sellers, key=lambda s: s.price)[0]
        
        return best_seller

    def action_create_purchase_order(self):
        """
        Main action called by the button.
        - Groups selected SO lines by vendor.
        - Finds or creates one draft PO per vendor.
        - Adds or updates PO lines for each product, preventing duplicates.
        """
        # A dictionary to group SO lines by vendor
        # e.g., {vendor_partner_1: [so_line_1, so_line_2], vendor_partner_2: [so_line_3]}
        vendor_lines = defaultdict(lambda: self.env['sale.order.line'])

        for line in self:
            # For each line, determine the best vendor
            seller = line._get_best_seller()
            vendor_lines[seller.partner_id] |= line

        if not vendor_lines:
            raise UserError(_("Could not determine a vendor for the selected lines."))

        purchase_orders = self.env['purchase.order']
        PurchaseOrderLine = self.env['purchase.order.line']

        # Create or update a PO for each vendor
        for vendor, so_lines in vendor_lines.items():
            # Find an existing draft PO for the vendor
            po = purchase_orders.search([
                ('partner_id', '=', vendor.id),
                ('state', '=', 'draft'),
            ], limit=1)

            # Or create a new one if it doesn't exist
            if not po:
                po = purchase_orders.create({
                    'partner_id': vendor.id,
                    # Use the name of the first SO as origin, or combine them
                    'origin': so_lines.order_id[0].name,
                })
            
            purchase_orders |= po

            # Process each SO line for the current vendor's PO
            for line in so_lines:
                # Check if a PO line for this product already exists on the PO
                po_line = PurchaseOrderLine.search([
                    ('order_id', '=', po.id),
                    ('product_id', '=', line.product_id.id),
                ], limit=1)

                seller = line._get_best_seller()

                if po_line:
                    # If it exists, update the quantity
                    po_line.product_qty += line.product_uom_qty
                else:
                    # Otherwise, create a new PO line
                    PurchaseOrderLine.create({
                        'order_id': po.id,
                        'product_id': line.product_id.id,
                        'product_qty': line.product_uom_qty,
                        'product_uom': line.product_id.uom_po_id.id,
                        'price_unit': seller.price, # Use price from the best seller
                        'date_planned': fields.Date.today(),
                    })
        
        # Return an action to open the created/updated purchase order(s)
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', purchase_orders.ids)],
        }
        if len(purchase_orders) == 1:
            # If only one PO was processed, open its form view directly
            action.update({
                'view_mode': 'form',
                'res_id': purchase_orders.id,
            })
        
        return action
