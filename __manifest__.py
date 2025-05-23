# -*- coding: utf-8 -*-
{
    'name': 'Odoo-Shopify Integration',
    'version': '1.0.0',
    'summary': 'Bi-directional synchronization between Shopify and Odoo',
    'description': """
Odoo-Shopify Bi-directional Integration
=======================================

This addon enables bi-directional synchronization between Shopify and Odoo, keeping product catalog,
inventory, vendors, orders, and product categories in sync.

Features:
---------
* Shopify → Odoo: Products, Variants, Images, Inventory, Vendors, Categories
* Odoo → Shopify: Products, Variants, Inventory adjustments, Vendor assignments
* Shopify Orders → Odoo: Orders, Customers, Sales Orders
* Automated CRON jobs for continuous synchronization
* Pagination support for large datasets
* Product Type mapping to Odoo Categories
* Automatic Dropshipping setup for products with vendors
* Configuration via System Parameters

Each task is implemented as a one-time callable method to support CRON automation.
    """,
    'category': 'Sales/Sales',
    'website': 'https://www.odoo.com',
    'author': 'Odoo Community',
    'depends': [
        'base',
        'product',
        'sale',
        'sales_team',
        'stock',
        'purchase',
        'contacts',
        'stock_dropshipping',
    ],
    'data': [
        'security/shopify_sync_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/shopify_sync_views.xml',
        'data/ir_cron_data.xml',
    ],
    'test': [
        'tests/test_shopify_sync.py',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
