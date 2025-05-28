# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Shopify synchronization fields
    x_shopify_updated_at = fields.Datetime(
        string='Shopify Last Updated',
        help='Timestamp when this product was last updated in Shopify'
    )
    x_shopify_synced_at = fields.Datetime(
        string='Last Synced to Shopify',
        help='Timestamp when this product was last synced to Shopify from Odoo'
    )
    description_html = fields.Html(
        string='Product Description (HTML)',
        help='The HTML description of the product from Shopify'
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # Shopify synchronization fields for variants
    x_shopify_variant_updated_at = fields.Datetime(
        string='Shopify Variant Last Updated',
        help='Timestamp when this variant was last updated in Shopify'
    )
