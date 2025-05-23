# -*- coding: utf-8 -*-

import requests
import re
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ShopifySync(models.Model):
    _name = 'shopify.sync'
    _description = 'Shopify Synchronization'
    _rec_name = 'name'

    name = fields.Char(string='Sync Name', required=True, default='Shopify Sync')
    last_sync_date = fields.Datetime(string='Last Sync Date')
    last_odoo_to_shopify_sync = fields.Datetime(string='Last Odoo to Shopify Sync')
    sync_status = fields.Selection([
        ('idle', 'Idle'),
        ('running', 'Running'),
        ('error', 'Error'),
        ('completed', 'Completed')
    ], string='Sync Status', default='idle')
    sync_log = fields.Text(string='Sync Log')

    @api.model
    def get_shopify_config(self):
        """Get Shopify configuration from system parameters"""
        config_param = self.env['ir.config_parameter'].sudo()
        return {
            'access_token': config_param.get_param('shopify.access_token'),
            'store_url': config_param.get_param('shopify.store_url'),
            'api_version': config_param.get_param('shopify.api_version', '2023-10'),
        }

    def _get_shopify_headers(self):
        """Get headers for Shopify API requests"""
        config = self.get_shopify_config()
        if not config['access_token']:
            raise UserError(_('Shopify access token is not configured. Please configure it in Settings.'))

        return {
            'X-Shopify-Access-Token': config['access_token'],
            'Content-Type': 'application/json',
        }

    def _get_shopify_url(self, endpoint):
        """Build Shopify API URL"""
        config = self.get_shopify_config()
        if not config['store_url']:
            raise UserError(_('Shopify store URL is not configured. Please configure it in Settings.'))

        base_url = config['store_url'].rstrip('/')
        api_version = config['api_version']
        return f"{base_url}/admin/api/{api_version}/{endpoint}"

    def _log_sync_message(self, message, level='info'):
        """Log sync messages"""
        timestamp = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {level.upper()}: {message}\n"

        if self.sync_log:
            self.sync_log += log_entry
        else:
            self.sync_log = log_entry

        if level == 'error':
            _logger.error(message)
        elif level == 'warning':
            _logger.warning(message)
        else:
            _logger.info(message)

    def parse_next_page_token(self, link_header):
        """Parse next page token from Link header"""
        if not link_header:
            return None
        match = re.search(r'page_info=([^&>]+)', link_header)
        return match.group(1) if match else None

    # ===== PRODUCT SYNCHRONIZATION METHODS =====

    @api.model
    def auto_sync_shopify_products(self):
        """Main method to sync Shopify products to Odoo"""
        try:
            self._log_sync_message("Starting Shopify products synchronization")
            self.sync_status = 'running'

            config_param = self.env['ir.config_parameter'].sudo()
            next_page = config_param.get_param('shopify.next_page')

            if not next_page:
                # First sync or reset - fetch products created this year
                products, next_page_token = self.fetch_shopify_products(limit=10, created_this_year=True)
                config_param.set_param('shopify.next_page', next_page_token or '')
                self.save_products_to_odoo(products)
            else:
                # Continue pagination
                products, next_page_token = self.fetch_shopify_products(limit=10, page_info=next_page)
                config_param.set_param('shopify.next_page', next_page_token or '')
                self.save_products_to_odoo(products)

            self.sync_status = 'completed'
            self.last_sync_date = fields.Datetime.now()
            self._log_sync_message(f"Successfully synced {len(products)} products")

        except Exception as e:
            self.sync_status = 'error'
            self._log_sync_message(f"Error during product sync: {str(e)}", 'error')
            raise

    def fetch_shopify_products(self, limit=10, page_info=None, created_this_year=False):
        """Fetch products from Shopify API"""
        try:
            headers = self._get_shopify_headers()
            params = {
                'limit': limit,
                'fields': 'id,title,variants,images,product_type,created_at,vendor,handle,status'
            }

            if page_info:
                params['page_info'] = page_info

            if created_this_year:
                current_year = fields.Date.today().year
                params['created_at_min'] = f"{current_year}-01-01T00:00:00Z"

            url = self._get_shopify_url('products.json')
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            products = data.get('products', [])
            next_page_token = self.parse_next_page_token(response.headers.get('Link'))

            self._log_sync_message(f"Fetched {len(products)} products from Shopify")
            return products, next_page_token

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error fetching products: {str(e)}", 'error')
            raise UserError(_('Failed to fetch products from Shopify: %s') % str(e))
        except Exception as e:
            self._log_sync_message(f"Unexpected error fetching products: {str(e)}", 'error')
            raise

    def save_products_to_odoo(self, products):
        """Save Shopify products to Odoo"""
        for product in products:
            try:
                self._save_single_product(product)
            except Exception as e:
                self._log_sync_message(f"Error saving product {product.get('title', 'Unknown')}: {str(e)}", 'error')
                continue

    def _save_single_product(self, shopify_product):
        """Save a single Shopify product to Odoo"""
        # Get or create product category
        category_name = shopify_product.get('product_type') or 'Uncategorized'
        category = self.env['product.category'].sudo().search([('name', '=', category_name)], limit=1)
        if not category:
            category = self.env['product.category'].sudo().create({'name': category_name})

        # Get or create vendor
        vendor_name = shopify_product.get('vendor')
        vendor = None
        if vendor_name:
            vendor = self.env['res.partner'].sudo().search([
                ('name', '=', vendor_name),
                ('is_company', '=', True),
                ('supplier_rank', '>', 0)
            ], limit=1)
            if not vendor:
                vendor = self.env['res.partner'].sudo().create({
                    'name': vendor_name,
                    'is_company': True,
                    'supplier_rank': 1,
                })

        # Check if product template already exists
        shopify_id = str(shopify_product['id'])
        existing_template = self.env['product.template'].sudo().search([
            ('default_code', '=', f"SHOPIFY_{shopify_id}")
        ], limit=1)

        # Prepare product template data
        template_vals = {
            'name': shopify_product['title'],
            'default_code': f"SHOPIFY_{shopify_id}",
            'categ_id': category.id,
            'type': 'product',
            'sale_ok': True,
            'purchase_ok': bool(vendor),
            'detailed_type': 'product',
        }

        # Store Shopify timestamps for sync tracking
        shopify_updated_at = shopify_product.get('updated_at')
        if shopify_updated_at:
            # Convert Shopify timestamp to Odoo datetime
            from datetime import datetime
            try:
                shopify_datetime = datetime.fromisoformat(shopify_updated_at.replace('Z', '+00:00'))
                template_vals['x_shopify_updated_at'] = shopify_datetime
            except:
                pass

        if vendor:
            template_vals['seller_ids'] = [(0, 0, {
                'partner_id': vendor.id,
                'min_qty': 1,
                'price': 0,  # Will be updated from variant data
            })]

            # Enable dropshipping if vendor exists
            try:
                dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
                if dropship_route:
                    template_vals['route_ids'] = [(6, 0, [dropship_route.id])]
                    self._log_sync_message(f"Enabled dropshipping for product with vendor: {vendor_name}")
                else:
                    self._log_sync_message("Dropshipping route not found - install stock_dropshipping module", 'warning')
            except Exception as e:
                self._log_sync_message(f"Error setting dropshipping route: {str(e)}", 'warning')

        if existing_template:
            existing_template.sudo().write(template_vals)
            product_template = existing_template
        else:
            product_template = self.env['product.template'].sudo().create(template_vals)

        # Handle variants
        variants = shopify_product.get('variants', [])
        for variant in variants:
            self._save_product_variant(product_template, variant, shopify_product)

        # Handle images
        images = shopify_product.get('images', [])
        if images:
            self._save_product_images(product_template, images)

        self._log_sync_message(f"Saved product: {shopify_product['title']}")

    def _save_product_variant(self, product_template, variant, shopify_product=None):
        """Save product variant"""
        shopify_variant_id = str(variant['id'])

        # Check if variant already exists
        existing_variant = self.env['product.product'].sudo().search([
            ('default_code', '=', f"SHOPIFY_VAR_{shopify_variant_id}")
        ], limit=1)

        variant_vals = {
            'product_tmpl_id': product_template.id,
            'default_code': f"SHOPIFY_VAR_{shopify_variant_id}",
            'barcode': variant.get('barcode'),
            'list_price': float(variant.get('price', 0)),
            'standard_price': float(variant.get('compare_at_price', 0)) if variant.get('compare_at_price') else float(variant.get('price', 0)),
            'weight': float(variant.get('weight', 0)),
        }

        if existing_variant:
            existing_variant.sudo().write(variant_vals)
            product_variant = existing_variant
        else:
            product_variant = self.env['product.product'].sudo().create(variant_vals)

        # Update inventory
        inventory_quantity = variant.get('inventory_quantity', 0)
        if inventory_quantity and inventory_quantity > 0:
            self._update_product_inventory(product_variant, inventory_quantity)

        return product_variant

    def _update_product_inventory(self, product_variant, quantity):
        """Update product inventory in Odoo"""
        try:
            # Find the main warehouse
            warehouse = self.env['stock.warehouse'].sudo().search([], limit=1)
            if not warehouse:
                self._log_sync_message("No warehouse found for inventory update", 'warning')
                return

            # Create inventory adjustment
            inventory_adjustment = self.env['stock.quant'].sudo().search([
                ('product_id', '=', product_variant.id),
                ('location_id', '=', warehouse.lot_stock_id.id)
            ], limit=1)

            if inventory_adjustment:
                inventory_adjustment.sudo().write({'quantity': quantity})
            else:
                self.env['stock.quant'].sudo().create({
                    'product_id': product_variant.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'quantity': quantity,
                })

        except Exception as e:
            self._log_sync_message(f"Error updating inventory for {product_variant.name}: {str(e)}", 'error')

    def _save_product_images(self, product_template, images):
        """Save product images"""
        try:
            import base64
            import urllib.request

            for i, image in enumerate(images[:5]):  # Limit to 5 images
                image_url = image.get('src')
                if not image_url:
                    continue

                try:
                    # Download image
                    with urllib.request.urlopen(image_url) as response:
                        image_data = response.read()
                        image_base64 = base64.b64encode(image_data).decode('utf-8')

                    if i == 0:
                        # First image as main product image
                        product_template.sudo().write({'image_1920': image_base64})
                    else:
                        # Additional images can be handled here if needed
                        pass

                except Exception as e:
                    self._log_sync_message(f"Error downloading image {image_url}: {str(e)}", 'warning')
                    continue

        except Exception as e:
            self._log_sync_message(f"Error saving images: {str(e)}", 'error')

    # ===== ORDER SYNCHRONIZATION METHODS =====

    @api.model
    def auto_sync_shopify_orders(self):
        """Main method to sync Shopify orders to Odoo"""
        try:
            self._log_sync_message("Starting Shopify orders synchronization")
            self.sync_status = 'running'

            config_param = self.env['ir.config_parameter'].sudo()
            next_page = config_param.get_param('shopify.orders_next_page')

            if not next_page:
                # First sync - fetch recent orders
                orders, next_page_token = self.fetch_shopify_orders(limit=10)
                config_param.set_param('shopify.orders_next_page', next_page_token or '')
                self.save_orders_to_odoo(orders)
            else:
                # Continue pagination
                orders, next_page_token = self.fetch_shopify_orders(limit=10, page_info=next_page)
                config_param.set_param('shopify.orders_next_page', next_page_token or '')
                self.save_orders_to_odoo(orders)

            self.sync_status = 'completed'
            self.last_sync_date = fields.Datetime.now()
            self._log_sync_message(f"Successfully synced {len(orders)} orders")

        except Exception as e:
            self.sync_status = 'error'
            self._log_sync_message(f"Error during order sync: {str(e)}", 'error')
            raise

    def fetch_shopify_orders(self, limit=10, page_info=None):
        """Fetch orders from Shopify API"""
        try:
            headers = self._get_shopify_headers()
            params = {
                'limit': limit,
                'status': 'any',
                'fields': 'id,name,email,created_at,updated_at,total_price,currency,customer,line_items,shipping_address,billing_address,financial_status,fulfillment_status'
            }

            if page_info:
                params['page_info'] = page_info

            url = self._get_shopify_url('orders.json')
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            orders = data.get('orders', [])
            next_page_token = self.parse_next_page_token(response.headers.get('Link'))

            self._log_sync_message(f"Fetched {len(orders)} orders from Shopify")
            return orders, next_page_token

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error fetching orders: {str(e)}", 'error')
            raise UserError(_('Failed to fetch orders from Shopify: %s') % str(e))
        except Exception as e:
            self._log_sync_message(f"Unexpected error fetching orders: {str(e)}", 'error')
            raise

    def save_orders_to_odoo(self, orders):
        """Save Shopify orders to Odoo"""
        for order in orders:
            try:
                self._save_single_order(order)
            except Exception as e:
                self._log_sync_message(f"Error saving order {order.get('name', 'Unknown')}: {str(e)}", 'error')
                continue

    def _save_single_order(self, shopify_order):
        """Save a single Shopify order to Odoo"""
        # Check if order already exists
        shopify_order_id = str(shopify_order['id'])
        existing_order = self.env['sale.order'].sudo().search([
            ('client_order_ref', '=', f"SHOPIFY_{shopify_order_id}")
        ], limit=1)

        if existing_order:
            self._log_sync_message(f"Order {shopify_order.get('name')} already exists, skipping")
            return existing_order

        # Get or create customer
        customer = self._get_or_create_customer(shopify_order)

        # Create sale order
        order_vals = {
            'partner_id': customer.id,
            'client_order_ref': f"SHOPIFY_{shopify_order_id}",
            'origin': shopify_order.get('name'),
            'date_order': shopify_order.get('created_at'),
            'state': 'draft',
            'currency_id': self._get_currency_id(shopify_order.get('currency', 'USD')),
        }

        sale_order = self.env['sale.order'].sudo().create(order_vals)

        # Add order lines
        line_items = shopify_order.get('line_items', [])
        for line_item in line_items:
            self._create_order_line(sale_order, line_item)

        # Confirm order if paid
        if shopify_order.get('financial_status') == 'paid':
            sale_order.sudo().action_confirm()

        self._log_sync_message(f"Created order: {shopify_order.get('name')}")
        return sale_order

    def _get_or_create_customer(self, shopify_order):
        """Get or create customer from Shopify order"""
        customer_data = shopify_order.get('customer', {})
        email = customer_data.get('email') or shopify_order.get('email')

        if not email:
            # Create anonymous customer
            return self.env['res.partner'].sudo().create({
                'name': 'Anonymous Customer',
                'is_company': False,
                'customer_rank': 1,
            })

        # Search for existing customer
        existing_customer = self.env['res.partner'].sudo().search([
            ('email', '=', email)
        ], limit=1)

        if existing_customer:
            return existing_customer

        # Create new customer
        customer_vals = {
            'name': f"{customer_data.get('first_name', '')} {customer_data.get('last_name', '')}".strip() or email,
            'email': email,
            'phone': customer_data.get('phone'),
            'is_company': False,
            'customer_rank': 1,
        }

        # Add shipping address
        shipping_address = shopify_order.get('shipping_address', {})
        if shipping_address:
            customer_vals.update({
                'street': shipping_address.get('address1'),
                'street2': shipping_address.get('address2'),
                'city': shipping_address.get('city'),
                'zip': shipping_address.get('zip'),
                'country_id': self._get_country_id(shipping_address.get('country_code')),
                'state_id': self._get_state_id(shipping_address.get('province_code'), shipping_address.get('country_code')),
            })

        return self.env['res.partner'].sudo().create(customer_vals)

    def _create_order_line(self, sale_order, line_item):
        """Create sale order line from Shopify line item"""
        # Find product by variant ID or SKU
        variant_id = line_item.get('variant_id')
        sku = line_item.get('sku')

        product = None
        if variant_id:
            product = self.env['product.product'].sudo().search([
                ('default_code', '=', f"SHOPIFY_VAR_{variant_id}")
            ], limit=1)

        if not product and sku:
            product = self.env['product.product'].sudo().search([
                ('default_code', '=', sku)
            ], limit=1)

        if not product:
            # Create a generic product
            product = self.env['product.product'].sudo().create({
                'name': line_item.get('title', 'Shopify Product'),
                'default_code': f"SHOPIFY_UNKNOWN_{line_item.get('id')}",
                'type': 'product',
                'list_price': float(line_item.get('price', 0)),
            })

        # Create order line
        line_vals = {
            'order_id': sale_order.id,
            'product_id': product.id,
            'name': line_item.get('title', product.name),
            'product_uom_qty': float(line_item.get('quantity', 1)),
            'price_unit': float(line_item.get('price', 0)),
        }

        return self.env['sale.order.line'].sudo().create(line_vals)

    # ===== UTILITY METHODS =====

    def _get_currency_id(self, currency_code):
        """Get currency ID by code"""
        currency = self.env['res.currency'].sudo().search([('name', '=', currency_code)], limit=1)
        if currency:
            return currency.id
        # Default to company currency
        return self.env.company.currency_id.id

    def _get_country_id(self, country_code):
        """Get country ID by code"""
        if not country_code:
            return False
        country = self.env['res.country'].sudo().search([('code', '=', country_code.upper())], limit=1)
        return country.id if country else False

    def _get_state_id(self, state_code, country_code):
        """Get state ID by code and country"""
        if not state_code or not country_code:
            return False

        country = self.env['res.country'].sudo().search([('code', '=', country_code.upper())], limit=1)
        if not country:
            return False

        state = self.env['res.country.state'].sudo().search([
            ('code', '=', state_code.upper()),
            ('country_id', '=', country.id)
        ], limit=1)
        return state.id if state else False

    # ===== EXPORT TO SHOPIFY METHODS =====

    @api.model
    def export_products_to_shopify(self):
        """Export Odoo products to Shopify"""
        try:
            self._log_sync_message("Starting product export to Shopify")
            self.sync_status = 'running'

            # Get products to export (products without Shopify ID)
            products_to_export = self.env['product.template'].sudo().search([
                ('sale_ok', '=', True),
                ('default_code', 'not like', 'SHOPIFY_%')
            ], limit=10)

            exported_count = 0
            for product in products_to_export:
                try:
                    self._export_single_product(product)
                    exported_count += 1
                except Exception as e:
                    self._log_sync_message(f"Error exporting product {product.name}: {str(e)}", 'error')
                    continue

            self.sync_status = 'completed'
            self.last_sync_date = fields.Datetime.now()
            self._log_sync_message(f"Successfully exported {exported_count} products to Shopify")

        except Exception as e:
            self.sync_status = 'error'
            self._log_sync_message(f"Error during product export: {str(e)}", 'error')
            raise

    def _export_single_product(self, product_template):
        """Export a single product to Shopify"""
        try:
            headers = self._get_shopify_headers()

            # Prepare product data
            product_data = {
                'product': {
                    'title': product_template.name,
                    'body_html': product_template.description_sale or '',
                    'vendor': product_template.seller_ids[0].partner_id.name if product_template.seller_ids else '',
                    'product_type': product_template.categ_id.name,
                    'status': 'active',
                    'variants': []
                }
            }

            # Add variants
            for variant in product_template.product_variant_ids:
                variant_data = {
                    'title': variant.name,
                    'price': str(variant.list_price),
                    'sku': variant.default_code or '',
                    'inventory_quantity': int(variant.qty_available),
                    'weight': variant.weight,
                    'barcode': variant.barcode or '',
                }
                product_data['product']['variants'].append(variant_data)

            # Send to Shopify
            url = self._get_shopify_url('products.json')
            response = requests.post(url, headers=headers, json=product_data, timeout=30)
            response.raise_for_status()

            # Update product with Shopify ID and sync timestamp
            shopify_product = response.json().get('product', {})
            shopify_id = shopify_product.get('id')
            if shopify_id:
                current_time = fields.Datetime.now()
                product_template.sudo().write({
                    'default_code': f"SHOPIFY_{shopify_id}",
                    'x_shopify_synced_at': current_time,
                    'x_shopify_updated_at': current_time
                })

            self._log_sync_message(f"Exported product: {product_template.name}")

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error exporting product: {str(e)}", 'error')
            raise
        except Exception as e:
            self._log_sync_message(f"Unexpected error exporting product: {str(e)}", 'error')
            raise

    # ===== INVENTORY SYNC TO SHOPIFY =====

    @api.model
    def sync_inventory_to_shopify(self):
        """Sync inventory changes from Odoo to Shopify"""
        try:
            self._log_sync_message("Starting inventory sync to Shopify")
            self.sync_status = 'running'

            # Get products that have Shopify IDs and need inventory updates
            shopify_products = self.env['product.template'].sudo().search([
                ('default_code', 'like', 'SHOPIFY_%'),
                ('sale_ok', '=', True)
            ], limit=50)

            updated_count = 0
            for product in shopify_products:
                try:
                    self._sync_product_inventory_to_shopify(product)
                    updated_count += 1
                except Exception as e:
                    self._log_sync_message(f"Error syncing inventory for {product.name}: {str(e)}", 'error')
                    continue

            self.sync_status = 'completed'
            self.last_sync_date = fields.Datetime.now()
            self._log_sync_message(f"Successfully synced inventory for {updated_count} products")

        except Exception as e:
            self.sync_status = 'error'
            self._log_sync_message(f"Error during inventory sync: {str(e)}", 'error')
            raise

    def _sync_product_inventory_to_shopify(self, product_template):
        """Sync inventory for a single product to Shopify"""
        try:
            # Extract Shopify product ID from default_code
            if not product_template.default_code or not product_template.default_code.startswith('SHOPIFY_'):
                return

            shopify_product_id = product_template.default_code.replace('SHOPIFY_', '')

            # Get product variants and their inventory
            for variant in product_template.product_variant_ids:
                if variant.default_code and variant.default_code.startswith('SHOPIFY_VAR_'):
                    shopify_variant_id = variant.default_code.replace('SHOPIFY_VAR_', '')
                    self._update_shopify_variant_inventory(shopify_variant_id, variant.qty_available)

        except Exception as e:
            self._log_sync_message(f"Error syncing inventory for product {product_template.name}: {str(e)}", 'error')
            raise

    def _update_shopify_variant_inventory(self, shopify_variant_id, quantity):
        """Update inventory for a specific Shopify variant"""
        try:
            headers = self._get_shopify_headers()

            # First, get the inventory item ID for this variant
            variant_url = self._get_shopify_url(f'variants/{shopify_variant_id}.json')
            variant_response = requests.get(variant_url, headers=headers, timeout=30)
            variant_response.raise_for_status()

            variant_data = variant_response.json().get('variant', {})
            inventory_item_id = variant_data.get('inventory_item_id')

            if not inventory_item_id:
                self._log_sync_message(f"No inventory item ID found for variant {shopify_variant_id}", 'warning')
                return

            # Get the location ID (first available location)
            locations_url = self._get_shopify_url('locations.json')
            locations_response = requests.get(locations_url, headers=headers, timeout=30)
            locations_response.raise_for_status()

            locations = locations_response.json().get('locations', [])
            if not locations:
                self._log_sync_message("No Shopify locations found for inventory update", 'warning')
                return

            location_id = locations[0]['id']  # Use first location

            # Update inventory level
            inventory_data = {
                'location_id': location_id,
                'inventory_item_id': inventory_item_id,
                'available': int(quantity)
            }

            inventory_url = self._get_shopify_url('inventory_levels/set.json')
            inventory_response = requests.post(inventory_url, headers=headers, json=inventory_data, timeout=30)
            inventory_response.raise_for_status()

            self._log_sync_message(f"Updated Shopify inventory for variant {shopify_variant_id}: {quantity}")

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error updating Shopify inventory: {str(e)}", 'error')
            raise
        except Exception as e:
            self._log_sync_message(f"Unexpected error updating Shopify inventory: {str(e)}", 'error')
            raise

    # ===== PRODUCT UPDATES TO SHOPIFY =====

    @api.model
    def update_products_to_shopify(self):
        """Update existing Shopify products with Odoo changes"""
        try:
            self._log_sync_message("Starting product updates to Shopify")
            self.sync_status = 'running'

            # Get last sync timestamp
            config_param = self.env['ir.config_parameter'].sudo()
            last_sync_str = config_param.get_param('shopify.last_odoo_to_shopify_sync')
            last_sync = None

            if last_sync_str:
                try:
                    from datetime import datetime
                    last_sync = datetime.fromisoformat(last_sync_str)
                except:
                    pass

            # Build domain to find products that need updating
            domain = [
                ('default_code', 'like', 'SHOPIFY_%'),
                ('sale_ok', '=', True)
            ]

            # Only update products modified since last sync
            if last_sync:
                domain.append(('write_date', '>', last_sync))
                self._log_sync_message(f"Looking for products modified since {last_sync}")
            else:
                self._log_sync_message("No previous sync found, checking all products")

            shopify_products = self.env['product.template'].sudo().search(domain, limit=20)

            updated_count = 0
            skipped_count = 0

            for product in shopify_products:
                try:
                    if self._should_update_product_in_shopify(product):
                        self._update_single_product_to_shopify(product)
                        updated_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    self._log_sync_message(f"Error updating product {product.name}: {str(e)}", 'error')
                    continue

            # Update last sync timestamp
            current_time = fields.Datetime.now()
            config_param.set_param('shopify.last_odoo_to_shopify_sync', current_time.isoformat())

            self.sync_status = 'completed'
            self.last_sync_date = current_time
            self.last_odoo_to_shopify_sync = current_time
            self._log_sync_message(f"Successfully updated {updated_count} products, skipped {skipped_count} products in Shopify")

        except Exception as e:
            self.sync_status = 'error'
            self._log_sync_message(f"Error during product updates: {str(e)}", 'error')
            raise

    def _should_update_product_in_shopify(self, product_template):
        """Check if product should be updated in Shopify based on timestamps"""
        try:
            # If no Shopify timestamp stored, update it
            if not product_template.x_shopify_updated_at:
                self._log_sync_message(f"No Shopify timestamp for {product_template.name}, will update")
                return True

            # Compare Odoo write_date with last sync timestamp
            odoo_updated = product_template.write_date
            last_synced = product_template.x_shopify_synced_at or product_template.x_shopify_updated_at

            if odoo_updated > last_synced:
                self._log_sync_message(f"Product {product_template.name} modified in Odoo since last sync, will update")
                return True
            else:
                self._log_sync_message(f"Product {product_template.name} is up to date, skipping")
                return False

        except Exception as e:
            self._log_sync_message(f"Error checking update status for {product_template.name}: {str(e)}", 'warning')
            # If we can't determine, err on the side of updating
            return True

    def _update_single_product_to_shopify(self, product_template):
        """Update a single product in Shopify"""
        try:
            # Extract Shopify product ID from default_code
            if not product_template.default_code or not product_template.default_code.startswith('SHOPIFY_'):
                return

            shopify_product_id = product_template.default_code.replace('SHOPIFY_', '')
            headers = self._get_shopify_headers()

            # Prepare updated product data
            product_data = {
                'product': {
                    'id': int(shopify_product_id),
                    'title': product_template.name,
                    'body_html': product_template.description_sale or '',
                    'vendor': product_template.seller_ids[0].partner_id.name if product_template.seller_ids else '',
                    'product_type': product_template.categ_id.name,
                    'status': 'active' if product_template.sale_ok else 'draft',
                }
            }

            # Update product in Shopify
            url = self._get_shopify_url(f'products/{shopify_product_id}.json')
            response = requests.put(url, headers=headers, json=product_data, timeout=30)
            response.raise_for_status()

            # Update variants
            for variant in product_template.product_variant_ids:
                if variant.default_code and variant.default_code.startswith('SHOPIFY_VAR_'):
                    self._update_shopify_variant(variant)

            # Update the sync timestamp to current time
            current_time = fields.Datetime.now()
            product_template.sudo().write({
                'x_shopify_synced_at': current_time,
                'x_shopify_updated_at': current_time
            })

            self._log_sync_message(f"Updated product in Shopify: {product_template.name}")

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error updating product: {str(e)}", 'error')
            raise
        except Exception as e:
            self._log_sync_message(f"Unexpected error updating product: {str(e)}", 'error')
            raise

    def _update_shopify_variant(self, product_variant):
        """Update a single variant in Shopify"""
        try:
            shopify_variant_id = product_variant.default_code.replace('SHOPIFY_VAR_', '')
            headers = self._get_shopify_headers()

            variant_data = {
                'variant': {
                    'id': int(shopify_variant_id),
                    'price': str(product_variant.list_price),
                    'sku': product_variant.default_code or '',
                    'weight': product_variant.weight,
                    'barcode': product_variant.barcode or '',
                }
            }

            url = self._get_shopify_url(f'variants/{shopify_variant_id}.json')
            response = requests.put(url, headers=headers, json=variant_data, timeout=30)
            response.raise_for_status()

            self._log_sync_message(f"Updated variant in Shopify: {product_variant.name}")

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error updating variant: {str(e)}", 'error')
            raise
        except Exception as e:
            self._log_sync_message(f"Unexpected error updating variant: {str(e)}", 'error')
            raise