# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Shopify Configuration
    shopify_access_token = fields.Char(
        string='Shopify Access Token',
        help='Private app access token from Shopify Admin API'
    )
    shopify_store_url = fields.Char(
        string='Shopify Store URL',
        help='Your Shopify store URL (e.g., https://your-store.myshopify.com)'
    )
    shopify_api_version = fields.Char(
        string='Shopify API Version',
        default='2023-10',
        help='Shopify API version to use'
    )

    # Sync Settings
    shopify_auto_sync_products = fields.Boolean(
        string='Auto Sync Products',
        help='Automatically sync products from Shopify to Odoo'
    )
    shopify_auto_sync_orders = fields.Boolean(
        string='Auto Sync Orders',
        help='Automatically sync orders from Shopify to Odoo'
    )
    shopify_auto_export_products = fields.Boolean(
        string='Auto Export Products',
        help='Automatically export products from Odoo to Shopify'
    )
    shopify_auto_publish_website = fields.Boolean(
        string='Auto Publish on Website',
        help='Automatically publish products fetched from Shopify on the Odoo website'
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        config_param = self.env['ir.config_parameter'].sudo()

        res.update(
            shopify_access_token=config_param.get_param('shopify.access_token', ''),
            shopify_store_url=config_param.get_param('shopify.store_url', ''),
            shopify_api_version=config_param.get_param('shopify.api_version', '2023-10'),
            shopify_auto_sync_products=config_param.get_param('shopify.auto_sync_products', False),
            shopify_auto_sync_orders=config_param.get_param('shopify.auto_sync_orders', False),
            shopify_auto_export_products=config_param.get_param('shopify.auto_export_products', False),
            shopify_auto_publish_website=config_param.get_param('shopify.auto_publish_website', False),
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        config_param = self.env['ir.config_parameter'].sudo()

        config_param.set_param('shopify.access_token', self.shopify_access_token or '')
        config_param.set_param('shopify.store_url', self.shopify_store_url or '')
        config_param.set_param('shopify.api_version', self.shopify_api_version or '2023-10')
        config_param.set_param('shopify.auto_sync_products', self.shopify_auto_sync_products)
        config_param.set_param('shopify.auto_sync_orders', self.shopify_auto_sync_orders)
        config_param.set_param('shopify.auto_export_products', self.shopify_auto_export_products)
        config_param.set_param('shopify.auto_publish_website', self.shopify_auto_publish_website)

    def test_shopify_connection(self):
        """Test Shopify API connection"""
        try:
            shopify_sync = self.env['shopify.sync'].create({'name': 'Connection Test'})
            config = shopify_sync.get_shopify_config()

            if not config['access_token'] or not config['store_url']:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Configuration Error',
                        'message': 'Please configure Shopify Access Token and Store URL first.',
                        'type': 'warning',
                    }
                }

            # Test API call
            import requests
            headers = {
                'X-Shopify-Access-Token': config['access_token'],
                'Content-Type': 'application/json',
            }

            url = f"{config['store_url'].rstrip('/')}/admin/api/{config['api_version']}/shop.json"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            shop_data = response.json().get('shop', {})
            shop_name = shop_data.get('name', 'Unknown')

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': f'Successfully connected to Shopify store: {shop_name}',
                    'type': 'success',
                }
            }

        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': f'Failed to connect to Shopify: {str(e)}',
                    'type': 'danger',
                }
            }
