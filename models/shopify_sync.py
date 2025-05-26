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
        sync_record = None
        try:
            # Get or create sync record
            sync_record = self.search([], limit=1)
            if not sync_record:
                sync_record = self.create({'name': 'Shopify Sync'})

            sync_record._log_sync_message("Starting Shopify products synchronization")
            sync_record.sync_status = 'running'

            config_param = self.env['ir.config_parameter'].sudo()
            next_page = config_param.get_param('shopify.next_page')
            current_page = int(config_param.get_param('shopify.current_page', '0'))

            if not next_page:
                # First sync or reset - fetch products created this year
                current_page = 1
                config_param.set_param('shopify.current_page', str(current_page))
                products, next_page_token = sync_record.fetch_shopify_products(limit=10, created_this_year=True, page_number=current_page)
                config_param.set_param('shopify.next_page', next_page_token or '')
                sync_record.save_products_to_odoo(products)
            else:
                # Continue pagination
                current_page += 1
                config_param.set_param('shopify.current_page', str(current_page))
                products, next_page_token = sync_record.fetch_shopify_products(limit=10, page_info=next_page, page_number=current_page)
                config_param.set_param('shopify.next_page', next_page_token or '')
                sync_record.save_products_to_odoo(products)

            sync_record.sync_status = 'completed'
            sync_record.last_sync_date = fields.Datetime.now()
            sync_record._log_sync_message(f"Successfully synced {len(products)} products")

            # If no more pages, reset pagination for next sync cycle
            if not next_page_token:
                config_param.set_param('shopify.current_page', '0')
                sync_record._log_sync_message("Completed all pages, pagination reset for next sync cycle")

        except Exception as e:
            if sync_record:
                sync_record.sync_status = 'error'
                sync_record._log_sync_message(f"Error during product sync: {str(e)}", 'error')
            else:
                _logger.error(f"Error during product sync: {str(e)}")
            # Don't re-raise to prevent cron job from failing completely
            return False

    def fetch_shopify_products(self, limit=10, page_info=None, created_this_year=False, page_number=1):
        """Fetch products from Shopify API"""
        try:
            headers = self._get_shopify_headers()
            params = {
                'limit': limit,
                'fields': 'id,title,variants,images,product_type,created_at,updated_at,vendor,handle,status'
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

            # Get total count and current progress
            total_count = self._get_total_products_count(created_this_year)
            current_count = self._get_current_synced_count()

            if total_count:
                self._log_sync_message(f"Page {page_number}: Fetched {len(products)} of {total_count} products from Shopify (Progress: {current_count + len(products)}/{total_count})")
            else:
                self._log_sync_message(f"Page {page_number}: Fetched {len(products)} products from Shopify")

            return products, next_page_token

        except requests.exceptions.RequestException as e:
            self._log_sync_message(f"HTTP error fetching products: {str(e)}", 'error')
            raise UserError(_('Failed to fetch products from Shopify: %s') % str(e))
        except Exception as e:
            self._log_sync_message(f"Unexpected error fetching products: {str(e)}", 'error')
            raise

    def _get_total_products_count(self, created_this_year=False):
        """Get total count of products from Shopify"""
        try:
            headers = self._get_shopify_headers()
            params = {
                'limit': 1,  # We only need the count, not the actual products
                'fields': 'id'  # Minimal field to reduce response size
            }

            if created_this_year:
                current_year = fields.Date.today().year
                params['created_at_min'] = f"{current_year}-01-01T00:00:00Z"

            url = self._get_shopify_url('products/count.json')
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            total_count = data.get('count', 0)

            # Store the total count for reference
            config_param = self.env['ir.config_parameter'].sudo()
            config_param.set_param('shopify.total_products_count', str(total_count))

            return total_count

        except Exception as e:
            self._log_sync_message(f"Could not get total products count: {str(e)}", 'warning')
            # Try to get cached count
            config_param = self.env['ir.config_parameter'].sudo()
            cached_count = config_param.get_param('shopify.total_products_count')
            return int(cached_count) if cached_count and cached_count.isdigit() else None

    def _get_current_synced_count(self):
        """Get count of products already synced from Shopify"""
        try:
            # Count products with Shopify IDs in Odoo
            synced_count = self.env['product.template'].sudo().search_count([
                ('default_code', 'like', 'SHOPIFY_%')
            ])
            return synced_count
        except Exception as e:
            self._log_sync_message(f"Could not get synced products count: {str(e)}", 'warning')
            return 0

    def _get_total_orders_count(self):
        """Get total count of orders from Shopify"""
        try:
            headers = self._get_shopify_headers()
            params = {
                'limit': 1,  # We only need the count, not the actual orders
                'status': 'any'
            }

            url = self._get_shopify_url('orders/count.json')
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            total_count = data.get('count', 0)

            # Store the total count for reference
            config_param = self.env['ir.config_parameter'].sudo()
            config_param.set_param('shopify.total_orders_count', str(total_count))

            return total_count

        except Exception as e:
            self._log_sync_message(f"Could not get total orders count: {str(e)}", 'warning')
            # Try to get cached count
            config_param = self.env['ir.config_parameter'].sudo()
            cached_count = config_param.get_param('shopify.total_orders_count')
            return int(cached_count) if cached_count and cached_count.isdigit() else None

    def _get_current_synced_orders_count(self):
        """Get count of orders already synced from Shopify"""
        try:
            # Count orders with Shopify IDs in Odoo
            synced_count = self.env['sale.order'].sudo().search_count([
                ('client_order_ref', 'like', 'SHOPIFY_%')
            ])
            return synced_count
        except Exception as e:
            self._log_sync_message(f"Could not get synced orders count: {str(e)}", 'warning')
            return 0

    def save_products_to_odoo(self, products):
        """Save Shopify products to Odoo"""
        processed_ids = set()  # Track processed Shopify IDs to avoid duplicates in same sync

        for product in products:
            # Use a savepoint for each product to isolate transaction errors
            try:
                shopify_id = str(product.get('id', ''))
                if shopify_id in processed_ids:
                    self._log_sync_message(f"Skipping duplicate product in same sync batch: {product.get('title', 'Unknown')} (ID: {shopify_id})", 'warning')
                    continue

                processed_ids.add(shopify_id)

                with self.env.cr.savepoint():
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

        # Check if product template already exists by Shopify ID (primary check)
        shopify_id = str(shopify_product['id'])
        existing_template = self.env['product.template'].sudo().search([
            ('default_code', '=', f"SHOPIFY_{shopify_id}")
        ], limit=1)

        # If no Shopify ID match, check by name (secondary check for manual products)
        if not existing_template:
            existing_template_name = self.env['product.template'].sudo().search([
                ('name', '=', shopify_product['title']),
                ('default_code', '=', False)  # Only check products without Shopify IDs
            ], limit=1)

            if existing_template_name:
                # Update the existing product with Shopify ID to link it
                existing_template_name.sudo().write({'default_code': f"SHOPIFY_{shopify_id}"})
                existing_template = existing_template_name
                self._log_sync_message(f"Linked existing product '{shopify_product['title']}' to Shopify ID {shopify_id}")
            else:
                # Check if there's already a Shopify product with the same name but different ID
                duplicate_shopify_product = self.env['product.template'].sudo().search([
                    ('name', '=', shopify_product['title']),
                    ('default_code', 'like', 'SHOPIFY_%'),
                    ('default_code', '!=', f"SHOPIFY_{shopify_id}")
                ], limit=1)

                if duplicate_shopify_product:
                    self._log_sync_message(f"Product with same name but different Shopify ID already exists: {shopify_product['title']} (existing: {duplicate_shopify_product.default_code}, new: SHOPIFY_{shopify_id})", 'warning')
                    # Skip this product to avoid creating duplicates
                    self._log_sync_message(f"Skipping product {shopify_product['title']} to avoid duplicate creation")
                    return

        # Determine if this is an update or creation
        is_update = bool(existing_template)
        action_type = "Updating" if is_update else "Creating"
        self._log_sync_message(f"{action_type} product: {shopify_product['title']} (Shopify ID: {shopify_id})")

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

        # Check if auto-publish on website is enabled
        config_param = self.env['ir.config_parameter'].sudo()
        auto_publish = config_param.get_param('shopify.auto_publish_website', False)

        if auto_publish:
            # Only publish if product status is 'active' in Shopify
            shopify_status = shopify_product.get('status', 'draft')
            if shopify_status == 'active':
                template_vals['is_published'] = True
                self._log_sync_message(f"Auto-publishing product on website: {shopify_product['title']}")
            else:
                template_vals['is_published'] = False
                self._log_sync_message(f"Product not published (Shopify status: {shopify_status}): {shopify_product['title']}")
        else:
            # Default to not published if auto-publish is disabled
            template_vals['is_published'] = False

        # Store Shopify timestamps for sync tracking
        shopify_updated_at = shopify_product.get('updated_at')
        if shopify_updated_at:
            # Convert Shopify timestamp to Odoo datetime
            from datetime import datetime, timezone
            try:
                shopify_datetime = datetime.fromisoformat(shopify_updated_at.replace('Z', '+00:00'))
                # Convert to UTC and make naive
                if shopify_datetime.tzinfo is not None:
                    shopify_datetime = shopify_datetime.astimezone(timezone.utc).replace(tzinfo=None)
                template_vals['x_shopify_updated_at'] = shopify_datetime
            except Exception as e:
                self._log_sync_message(f"Error converting datetime: {str(e)}", 'warning')

        # Handle vendor assignment (avoid duplicates)
        if vendor:
            # Check if vendor is already associated with this product
            vendor_already_exists = False
            if existing_template:
                existing_vendor = existing_template.seller_ids.filtered(lambda s: s.partner_id.id == vendor.id)
                if existing_vendor:
                    vendor_already_exists = True
                    self._log_sync_message(f"Vendor {vendor_name} already associated with product {shopify_product['title']}")

            if not vendor_already_exists:
                # For new products, add vendor to template_vals
                # For existing products, we'll add the vendor separately after the write operation
                if not existing_template:
                    template_vals['seller_ids'] = [(0, 0, {
                        'partner_id': vendor.id,
                        'min_qty': 1,
                        'price': 0,  # Will be updated from variant data
                    })]
                    self._log_sync_message(f"Adding vendor {vendor_name} to new product {shopify_product['title']}")
                # For existing products, we'll handle vendor addition after the template update

            # Enable dropshipping if vendor exists (only for new products or if not already set)
            try:
                dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
                if dropship_route:
                    # Check if dropshipping is already enabled
                    dropship_already_enabled = False
                    if existing_template and dropship_route.id in existing_template.route_ids.ids:
                        dropship_already_enabled = True

                    if not dropship_already_enabled:
                        # Get existing routes and add dropshipping route
                        existing_routes = existing_template.route_ids.ids if existing_template else []
                        if dropship_route.id not in existing_routes:
                            existing_routes.append(dropship_route.id)
                        template_vals['route_ids'] = [(6, 0, existing_routes)]
                        self._log_sync_message(f"Enabled dropshipping for product with vendor: {vendor_name}")
                    else:
                        self._log_sync_message(f"Dropshipping already enabled for product: {shopify_product['title']}")
                else:
                    self._log_sync_message("Dropshipping route not found - install stock_dropshipping module", 'warning')
            except Exception as e:
                self._log_sync_message(f"Error setting dropshipping route: {str(e)}", 'warning')

        if existing_template:
            # Update existing product
            try:
                existing_template.sudo().write(template_vals)
                product_template = existing_template
                self._log_sync_message(f"Successfully updated product template: {shopify_product['title']}")

                # Handle vendor addition for existing products (after template update)
                if vendor and not vendor_already_exists:
                    try:
                        # Double-check if vendor was already added to avoid duplicates
                        existing_supplier = self.env['product.supplierinfo'].sudo().search([
                            ('partner_id', '=', vendor.id),
                            ('product_tmpl_id', '=', product_template.id)
                        ], limit=1)

                        if not existing_supplier:
                            # Create vendor line for existing product
                            self.env['product.supplierinfo'].sudo().create({
                                'partner_id': vendor.id,
                                'product_tmpl_id': product_template.id,
                                'min_qty': 1,
                                'price': 0,  # Will be updated from variant data
                            })
                            self._log_sync_message(f"Added vendor {vendor_name} to existing product {shopify_product['title']}")
                        else:
                            self._log_sync_message(f"Vendor {vendor_name} already exists for product {shopify_product['title']}")
                    except Exception as e:
                        self._log_sync_message(f"Error adding vendor to existing product: {str(e)}", 'warning')

                # Log publication status change for existing products
                if auto_publish and 'is_published' in template_vals:
                    if template_vals['is_published']:
                        self._log_sync_message(f"Updated existing product publication status to published: {shopify_product['title']}")
                    else:
                        self._log_sync_message(f"Updated existing product publication status to unpublished: {shopify_product['title']}")

            except Exception as e:
                self._log_sync_message(f"Error updating existing product template: {str(e)}", 'error')
                raise
        else:
            # Create new product
            try:
                product_template = self.env['product.template'].sudo().create(template_vals)
                self._log_sync_message(f"Successfully created new product template: {shopify_product['title']}")
            except Exception as e:
                self._log_sync_message(f"Error creating new product template: {str(e)}", 'error')
                raise

        # Handle variants
        variants = shopify_product.get('variants', [])
        created_variants = []
        for variant in variants:
            variant_obj = self._save_product_variant(product_template, variant, shopify_product)
            if variant_obj:
                created_variants.append(variant_obj)

        # Verify all variants are properly linked
        self._verify_variant_linkage(product_template, created_variants)

        # Handle images
        images = shopify_product.get('images', [])
        if images:
            self._save_product_images(product_template, images)

        self._log_sync_message(f"Saved product: {shopify_product['title']}")

    def _process_variant_attributes(self, variant, product_template, shopify_product=None):
        """Process Shopify variant attributes and create/link them in Odoo"""
        attribute_value_ids = []

        try:
            # Shopify variants have option1, option2, option3 fields
            variant_options = []
            for i in range(1, 4):  # option1, option2, option3
                option_value = variant.get(f'option{i}')
                if option_value and option_value.lower() != 'default title':
                    variant_options.append((i, option_value))

            if not variant_options:
                # No variant options, this is a simple product
                return attribute_value_ids

            # Get attribute names from Shopify product options if available
            option_names = {}
            if shopify_product and 'options' in shopify_product:
                for option in shopify_product['options']:
                    position = option.get('position', 1)
                    name = option.get('name', f'Option {position}')
                    option_names[position] = name

            # Get or create product attributes and values
            for option_index, option_value in variant_options:
                # Use meaningful attribute name from Shopify or fallback
                attribute_name = option_names.get(option_index, f"Shopify Option {option_index}")

                # Get or create the product attribute
                product_attribute = self.env['product.attribute'].sudo().search([
                    ('name', '=', attribute_name)
                ], limit=1)

                if not product_attribute:
                    product_attribute = self.env['product.attribute'].sudo().create({
                        'name': attribute_name,
                        'display_type': 'radio',  # or 'select'
                        'create_variant': 'always'
                    })
                    self._log_sync_message(f"Created product attribute: {attribute_name}")

                # Get or create the attribute value
                attribute_value = self.env['product.attribute.value'].sudo().search([
                    ('attribute_id', '=', product_attribute.id),
                    ('name', '=', option_value)
                ], limit=1)

                if not attribute_value:
                    attribute_value = self.env['product.attribute.value'].sudo().create({
                        'attribute_id': product_attribute.id,
                        'name': option_value
                    })
                    self._log_sync_message(f"Created attribute value: {option_value} for {attribute_name}")

                # Check if this attribute is already linked to the product template
                template_attribute = self.env['product.template.attribute.line'].sudo().search([
                    ('product_tmpl_id', '=', product_template.id),
                    ('attribute_id', '=', product_attribute.id)
                ], limit=1)

                if not template_attribute:
                    # Link the attribute to the product template
                    template_attribute = self.env['product.template.attribute.line'].sudo().create({
                        'product_tmpl_id': product_template.id,
                        'attribute_id': product_attribute.id,
                        'value_ids': [(6, 0, [attribute_value.id])]
                    })
                    self._log_sync_message(f"Linked attribute {attribute_name} to product template")
                else:
                    # Add the value to existing attribute line if not already there
                    if attribute_value.id not in template_attribute.value_ids.ids:
                        template_attribute.sudo().write({
                            'value_ids': [(4, attribute_value.id)]
                        })
                        self._log_sync_message(f"Added value {option_value} to existing attribute {attribute_name}")

                # Get the product template attribute value (the link between template and attribute value)
                template_attribute_value = self.env['product.template.attribute.value'].sudo().search([
                    ('product_tmpl_id', '=', product_template.id),
                    ('attribute_id', '=', product_attribute.id),
                    ('product_attribute_value_id', '=', attribute_value.id)
                ], limit=1)

                if template_attribute_value:
                    attribute_value_ids.append(template_attribute_value.id)

        except Exception as e:
            self._log_sync_message(f"Error processing variant attributes: {str(e)}", 'warning')

        return attribute_value_ids

    def _save_product_variant(self, product_template, variant, shopify_product=None):
        """Save product variant with proper attributes"""
        shopify_variant_id = str(variant['id'])

        # Check if variant already exists by Shopify variant ID
        existing_variant = self.env['product.product'].sudo().search([
            ('default_code', '=', f"SHOPIFY_VAR_{shopify_variant_id}")
        ], limit=1)

        # Handle variant attributes from Shopify
        attribute_value_ids = self._process_variant_attributes(variant, product_template, shopify_product)

        # Handle barcode carefully to avoid duplicates
        shopify_barcode = variant.get('barcode')
        barcode_to_use = None

        if shopify_barcode:
            # Check if this barcode is already used by another product
            existing_barcode_product = self.env['product.product'].sudo().search([
                ('barcode', '=', shopify_barcode),
                ('id', '!=', existing_variant.id if existing_variant else 0)
            ], limit=1)

            if existing_barcode_product:
                self._log_sync_message(f"Barcode {shopify_barcode} already used by product {existing_barcode_product.name}, skipping barcode assignment", 'warning')
                barcode_to_use = None
            else:
                barcode_to_use = shopify_barcode

        variant_vals = {
            'default_code': f"SHOPIFY_VAR_{shopify_variant_id}",
            'list_price': float(variant.get('price', 0)),
            'standard_price': float(variant.get('compare_at_price', 0)) if variant.get('compare_at_price') else float(variant.get('price', 0)),
            'weight': float(variant.get('weight', 0)),
        }

        # Only set barcode if it's safe to do so
        if barcode_to_use:
            variant_vals['barcode'] = barcode_to_use

        # Add attribute values if any were processed
        if attribute_value_ids:
            variant_vals['product_template_attribute_value_ids'] = [(6, 0, attribute_value_ids)]

        if existing_variant:
            # Check if the existing variant is already linked to the correct template
            if existing_variant.product_tmpl_id.id == product_template.id:
                # Same template, safe to update
                try:
                    existing_variant.sudo().write(variant_vals)
                    product_variant = existing_variant
                    self._log_sync_message(f"Updated existing variant {shopify_variant_id} for product {product_template.name}")
                except Exception as e:
                    # Even updating the same template can cause constraint violations
                    self._log_sync_message(f"Error updating existing variant: {str(e)}", 'warning')
                    # Try to find another variant to update or use the existing one as-is
                    product_variant = existing_variant
            else:
                # Different template - this could cause constraint violation
                # Check if there's already a variant for this template that we can use
                template_variant = self.env['product.product'].sudo().search([
                    ('product_tmpl_id', '=', product_template.id),
                    ('default_code', '=', False)  # Look for default variant first
                ], limit=1)

                if not template_variant:
                    # No default variant, look for any variant
                    template_variant = self.env['product.product'].sudo().search([
                        ('product_tmpl_id', '=', product_template.id)
                    ], limit=1)

                if template_variant:
                    # Update the existing template variant with Shopify data
                    try:
                        template_variant.sudo().write(variant_vals)
                        product_variant = template_variant
                        self._log_sync_message(f"Updated template variant {template_variant.id} with Shopify data for product {product_template.name}")
                    except Exception as e:
                        # If updating template variant fails, just use it as-is
                        self._log_sync_message(f"Could not update template variant, using as-is: {str(e)}", 'warning')
                        product_variant = template_variant
                else:
                    # No existing variant for this template, try to create new one
                    try:
                        variant_vals['product_tmpl_id'] = product_template.id
                        product_variant = self.env['product.product'].sudo().create(variant_vals)
                        self._log_sync_message(f"Created new variant {shopify_variant_id} for product {product_template.name}")
                    except Exception as e:
                        # Creation failed, update the existing variant but don't change template
                        self._log_sync_message(f"Could not create new variant, updating existing: {str(e)}", 'warning')
                        # Remove product_tmpl_id from vals to avoid constraint violation
                        variant_vals_safe = {k: v for k, v in variant_vals.items() if k != 'product_tmpl_id'}
                        try:
                            existing_variant.sudo().write(variant_vals_safe)
                            product_variant = existing_variant
                        except Exception as e2:
                            # Even safe update failed, just use existing variant as-is
                            self._log_sync_message(f"Could not update variant at all, using as-is: {str(e2)}", 'warning')
                            product_variant = existing_variant
        else:
            # For new variants, check if the template already has a default variant we can use
            existing_template_variant = self.env['product.product'].sudo().search([
                ('product_tmpl_id', '=', product_template.id)
            ], limit=1)

            if existing_template_variant:
                # Template already has a variant (probably the auto-created default one)
                # Update it with our Shopify data instead of creating a new one
                try:
                    existing_template_variant.sudo().write(variant_vals)
                    product_variant = existing_template_variant
                    self._log_sync_message(f"Updated existing template variant {existing_template_variant.id} with Shopify data for product {product_template.name}")
                except Exception as e:
                    # If update fails, use the variant as-is
                    self._log_sync_message(f"Could not update template variant, using as-is: {str(e)}", 'warning')
                    product_variant = existing_template_variant
            else:
                # No existing variant, safe to create new one
                try:
                    variant_vals['product_tmpl_id'] = product_template.id
                    product_variant = self.env['product.product'].sudo().create(variant_vals)
                    self._log_sync_message(f"Created new variant {shopify_variant_id} for product {product_template.name}")
                except Exception as e:
                    # Creation failed, this shouldn't happen but handle it gracefully
                    self._log_sync_message(f"Variant creation failed unexpectedly: {str(e)}", 'error')
                    # Try to find any variant that might have been created
                    fallback_variant = self.env['product.product'].sudo().search([
                        ('product_tmpl_id', '=', product_template.id)
                    ], limit=1)
                    if fallback_variant:
                        product_variant = fallback_variant
                        self._log_sync_message(f"Using fallback variant {fallback_variant.id}")
                    else:
                        # Last resort: create minimal variant
                        try:
                            minimal_variant = self.env['product.product'].sudo().create({
                                'product_tmpl_id': product_template.id,
                                'default_code': f"SHOPIFY_VAR_{shopify_variant_id}",
                            })
                            product_variant = minimal_variant
                            self._log_sync_message(f"Created minimal fallback variant for product {product_template.name}")
                        except Exception as e2:
                            self._log_sync_message(f"Could not create any variant: {str(e2)}", 'error')
                            raise

        # Verify the variant is properly linked
        if product_variant.product_tmpl_id.id != product_template.id:
            self._log_sync_message(f"Warning: Variant {shopify_variant_id} not properly linked to template {product_template.name}", 'warning')

        # Update inventory
        inventory_quantity = variant.get('inventory_quantity', 0)
        if inventory_quantity and inventory_quantity > 0:
            self._update_product_inventory(product_variant, inventory_quantity)

        return product_variant

    def _verify_variant_linkage(self, product_template, created_variants):
        """Verify that all variants are properly linked to the product template"""
        try:
            # Get all variants that should be linked to this template
            template_variants = self.env['product.product'].sudo().search([
                ('product_tmpl_id', '=', product_template.id)
            ])

            self._log_sync_message(f"Product template {product_template.name} has {len(template_variants)} linked variants")

            # Check if any created variants are missing from the template
            for variant in created_variants:
                if variant.product_tmpl_id.id != product_template.id:
                    self._log_sync_message(f"ERROR: Variant {variant.default_code} not linked to template {product_template.name}", 'error')
                    # Try to fix the linkage
                    try:
                        variant.sudo().write({'product_tmpl_id': product_template.id})
                        self._log_sync_message(f"Fixed variant linkage for {variant.default_code}", 'warning')
                    except Exception as e:
                        self._log_sync_message(f"Failed to fix variant linkage: {str(e)}", 'error')

        except Exception as e:
            self._log_sync_message(f"Error verifying variant linkage: {str(e)}", 'error')

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
        sync_record = None
        try:
            # Get or create sync record
            sync_record = self.search([], limit=1)
            if not sync_record:
                sync_record = self.create({'name': 'Shopify Sync'})

            sync_record._log_sync_message("Starting Shopify orders synchronization")
            sync_record.sync_status = 'running'

            config_param = self.env['ir.config_parameter'].sudo()
            next_page = config_param.get_param('shopify.orders_next_page')
            current_page = int(config_param.get_param('shopify.orders_current_page', '0'))

            if not next_page:
                # First sync - fetch recent orders
                current_page = 1
                config_param.set_param('shopify.orders_current_page', str(current_page))
                orders, next_page_token = sync_record.fetch_shopify_orders(limit=50, page_number=current_page)
                config_param.set_param('shopify.orders_next_page', next_page_token or '')
                sync_record.save_orders_to_odoo(orders)
            else:
                # Continue pagination
                current_page += 1
                config_param.set_param('shopify.orders_current_page', str(current_page))
                orders, next_page_token = sync_record.fetch_shopify_orders(limit=50, page_info=next_page, page_number=current_page)
                config_param.set_param('shopify.orders_next_page', next_page_token or '')
                sync_record.save_orders_to_odoo(orders)

            sync_record.sync_status = 'completed'
            sync_record.last_sync_date = fields.Datetime.now()
            sync_record._log_sync_message(f"Successfully synced {len(orders)} orders")

            # If no more pages, reset pagination for next sync cycle
            if not next_page_token:
                config_param.set_param('shopify.orders_current_page', '0')
                sync_record._log_sync_message("Completed all order pages, pagination reset for next sync cycle")

        except Exception as e:
            if sync_record:
                sync_record.sync_status = 'error'
                sync_record._log_sync_message(f"Error during order sync: {str(e)}", 'error')
            else:
                _logger.error(f"Error during order sync: {str(e)}")
            # Don't re-raise to prevent cron job from failing completely
            return False

    def fetch_shopify_orders(self, limit=50, page_info=None, page_number=1):
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

            # Get total count and current progress for orders
            total_count = self._get_total_orders_count()
            current_count = self._get_current_synced_orders_count()

            if total_count:
                self._log_sync_message(f"Page {page_number}: Fetched {len(orders)} of {total_count} orders from Shopify (Progress: {current_count + len(orders)}/{total_count})")
            else:
                self._log_sync_message(f"Page {page_number}: Fetched {len(orders)} orders from Shopify")

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
            # Use a savepoint for each order to isolate transaction errors
            try:
                with self.env.cr.savepoint():
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
                    from datetime import datetime, timezone
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