# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from unittest.mock import patch, MagicMock


class TestShopifySync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.shopify_sync = self.env['shopify.sync'].create({
            'name': 'Test Shopify Sync'
        })

        # Mock Shopify configuration
        self.env['ir.config_parameter'].sudo().set_param('shopify.access_token', 'test_token')
        self.env['ir.config_parameter'].sudo().set_param('shopify.store_url', 'https://test-store.myshopify.com')
        self.env['ir.config_parameter'].sudo().set_param('shopify.api_version', '2023-10')

    def test_duplicate_variant_handling(self):
        """Test that duplicate product variants are handled gracefully"""

        # Create a product template first
        product_template = self.env['product.template'].create({
            'name': 'Test Product',
            'default_code': 'SHOPIFY_123',
            'type': 'product',
        })

        # Create a variant manually to simulate existing data
        existing_variant = self.env['product.product'].create({
            'product_tmpl_id': product_template.id,
            'default_code': 'EXISTING_VAR',
        })

        # Mock Shopify variant data
        shopify_variant = {
            'id': 456,
            'price': '29.99',
            'weight': 1.5,
            'barcode': 'TEST123',
            'inventory_quantity': 10
        }

        # Test that variant creation handles duplicates
        result_variant = self.shopify_sync._save_product_variant(
            product_template,
            shopify_variant
        )

        # Should return the existing variant (updated)
        self.assertEqual(result_variant.product_tmpl_id, product_template)
        self.assertEqual(result_variant.default_code, 'SHOPIFY_VAR_456')

    def test_transaction_isolation(self):
        """Test that transaction errors are isolated per product"""

        # Mock products data - one good, one that will cause error
        mock_products = [
            {
                'id': 123,
                'title': 'Good Product',
                'variants': [{'id': 456, 'price': '19.99'}],
                'images': [],
                'product_type': 'Test Category',
                'vendor': 'Test Vendor'
            },
            {
                'id': 124,
                'title': 'Bad Product',
                'variants': [{'id': 457, 'price': 'invalid_price'}],  # This will cause error
                'images': [],
                'product_type': 'Test Category',
                'vendor': 'Test Vendor'
            }
        ]

        # Test that one failing product doesn't break the entire sync
        self.shopify_sync.save_products_to_odoo(mock_products)

        # Check that the good product was created
        good_product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_123')
        ])
        self.assertTrue(good_product, "Good product should be created despite other product failing")

    @patch('requests.get')
    def test_sync_error_handling(self, mock_get):
        """Test that sync errors are handled gracefully"""

        # Mock a failed API response
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_get.return_value = mock_response

        # Test that sync doesn't crash on API errors
        result = self.shopify_sync.auto_sync_shopify_products()

        # Should return False and set error status
        self.assertFalse(result)
        self.assertEqual(self.shopify_sync.sync_status, 'error')

    def test_variant_update_existing(self):
        """Test updating existing variants"""

        # Create existing product and variant
        product_template = self.env['product.template'].create({
            'name': 'Existing Product',
            'default_code': 'SHOPIFY_789',
        })

        existing_variant = self.env['product.product'].create({
            'product_tmpl_id': product_template.id,
            'default_code': 'SHOPIFY_VAR_999',
            'list_price': 10.0,
        })

        # Mock updated variant data
        updated_variant_data = {
            'id': 999,
            'price': '25.99',
            'weight': 2.0,
            'barcode': 'UPDATED123',
        }

        # Update the variant
        result = self.shopify_sync._save_product_variant(
            product_template,
            updated_variant_data
        )

        # Check that existing variant was updated
        self.assertEqual(result.id, existing_variant.id)
        self.assertEqual(result.list_price, 25.99)
        self.assertEqual(result.weight, 2.0)
        self.assertEqual(result.barcode, 'UPDATED123')

    def test_auto_publish_website_enabled(self):
        """Test that products are auto-published when setting is enabled"""

        # Enable auto-publish setting
        self.env['ir.config_parameter'].sudo().set_param('shopify.auto_publish_website', True)

        # Mock Shopify product data with active status
        shopify_product = {
            'id': 789,
            'title': 'Auto Publish Test Product',
            'status': 'active',
            'variants': [{'id': 101112, 'price': '39.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product was created and published
        product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_789')
        ])
        self.assertTrue(product, "Product should be created")
        self.assertTrue(product.is_published, "Product should be published on website")

    def test_auto_publish_website_disabled(self):
        """Test that products are not auto-published when setting is disabled"""

        # Disable auto-publish setting
        self.env['ir.config_parameter'].sudo().set_param('shopify.auto_publish_website', False)

        # Mock Shopify product data with active status
        shopify_product = {
            'id': 790,
            'title': 'No Auto Publish Test Product',
            'status': 'active',
            'variants': [{'id': 101113, 'price': '49.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product was created but not published
        product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_790')
        ])
        self.assertTrue(product, "Product should be created")
        self.assertFalse(product.is_published, "Product should not be published on website")

    def test_auto_publish_inactive_product(self):
        """Test that inactive Shopify products are not published even with auto-publish enabled"""

        # Enable auto-publish setting
        self.env['ir.config_parameter'].sudo().set_param('shopify.auto_publish_website', True)

        # Mock Shopify product data with draft status
        shopify_product = {
            'id': 791,
            'title': 'Inactive Product Test',
            'status': 'draft',
            'variants': [{'id': 101114, 'price': '59.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product was created but not published
        product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_791')
        ])
        self.assertTrue(product, "Product should be created")
        self.assertFalse(product.is_published, "Inactive product should not be published on website")

    def test_no_duplicate_vendors(self):
        """Test that vendors are not duplicated when syncing the same product multiple times"""

        # Create a vendor first
        vendor = self.env['res.partner'].create({
            'name': 'Test Vendor',
            'is_company': True,
            'supplier_rank': 1,
        })

        # Mock Shopify product data
        shopify_product = {
            'id': 792,
            'title': 'Vendor Test Product',
            'status': 'active',
            'variants': [{'id': 101115, 'price': '69.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product first time
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product was created with vendor
        product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_792')
        ])
        self.assertTrue(product, "Product should be created")
        self.assertEqual(len(product.seller_ids), 1, "Product should have exactly one vendor")
        self.assertEqual(product.seller_ids[0].partner_id.name, 'Test Vendor', "Vendor should be Test Vendor")

        # Save the same product again (simulate re-sync)
        self.shopify_sync._save_single_product(shopify_product)

        # Refresh the product record
        product.invalidate_recordset()

        # Check that vendor was not duplicated
        self.assertEqual(len(product.seller_ids), 1, "Product should still have exactly one vendor (no duplicates)")
        self.assertEqual(product.seller_ids[0].partner_id.name, 'Test Vendor', "Vendor should still be Test Vendor")

    def test_different_vendors_are_added(self):
        """Test that different vendors can be added to the same product"""

        # Create vendors
        vendor1 = self.env['res.partner'].create({
            'name': 'Vendor One',
            'is_company': True,
            'supplier_rank': 1,
        })
        vendor2 = self.env['res.partner'].create({
            'name': 'Vendor Two',
            'is_company': True,
            'supplier_rank': 1,
        })

        # Mock Shopify product data with first vendor
        shopify_product = {
            'id': 793,
            'title': 'Multi Vendor Test Product',
            'status': 'active',
            'variants': [{'id': 101116, 'price': '79.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Vendor One'
        }

        # Save the product with first vendor
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product was created with first vendor
        product = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_793')
        ])
        self.assertTrue(product, "Product should be created")
        self.assertEqual(len(product.seller_ids), 1, "Product should have exactly one vendor")
        self.assertEqual(product.seller_ids[0].partner_id.name, 'Vendor One', "First vendor should be Vendor One")

        # Update product with different vendor
        shopify_product['vendor'] = 'Vendor Two'
        self.shopify_sync._save_single_product(shopify_product)

        # Refresh the product record
        product.invalidate_recordset()

        # Check that second vendor was added (not replaced)
        self.assertEqual(len(product.seller_ids), 2, "Product should now have two vendors")
        vendor_names = [seller.partner_id.name for seller in product.seller_ids]
        self.assertIn('Vendor One', vendor_names, "First vendor should still be present")
        self.assertIn('Vendor Two', vendor_names, "Second vendor should be added")

    def test_variant_linkage_to_template(self):
        """Test that product variants are properly linked to their template"""

        # Mock Shopify product data with multiple variants
        shopify_product = {
            'id': 794,
            'title': 'Multi Variant Product',
            'status': 'active',
            'variants': [
                {'id': 101117, 'price': '89.99', 'title': 'Small'},
                {'id': 101118, 'price': '99.99', 'title': 'Medium'},
                {'id': 101119, 'price': '109.99', 'title': 'Large'}
            ],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product
        self.shopify_sync._save_single_product(shopify_product)

        # Check that product template was created
        product_template = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_794')
        ])
        self.assertTrue(product_template, "Product template should be created")

        # Check that all variants are properly linked to the template
        linked_variants = self.env['product.product'].search([
            ('product_tmpl_id', '=', product_template.id)
        ])

        # Should have at least the variants we created
        self.assertGreaterEqual(len(linked_variants), 3, "Template should have at least 3 linked variants")

        # Check that Shopify variants exist and are linked
        shopify_variants = self.env['product.product'].search([
            ('default_code', 'in', ['SHOPIFY_VAR_101117', 'SHOPIFY_VAR_101118', 'SHOPIFY_VAR_101119'])
        ])

        self.assertEqual(len(shopify_variants), 3, "All 3 Shopify variants should be created")

        # Verify each variant is linked to the correct template
        for variant in shopify_variants:
            self.assertEqual(variant.product_tmpl_id.id, product_template.id,
                           f"Variant {variant.default_code} should be linked to template {product_template.name}")

    def test_variant_update_preserves_linkage(self):
        """Test that updating variants preserves their linkage to the template"""

        # Create initial product
        shopify_product = {
            'id': 795,
            'title': 'Update Test Product',
            'status': 'active',
            'variants': [{'id': 101120, 'price': '119.99'}],
            'images': [],
            'product_type': 'Test Category',
            'vendor': 'Test Vendor'
        }

        # Save the product first time
        self.shopify_sync._save_single_product(shopify_product)

        # Get the created template and variant
        product_template = self.env['product.template'].search([
            ('default_code', '=', 'SHOPIFY_795')
        ])
        original_variant = self.env['product.product'].search([
            ('default_code', '=', 'SHOPIFY_VAR_101120')
        ])

        self.assertTrue(product_template, "Product template should be created")
        self.assertTrue(original_variant, "Product variant should be created")
        self.assertEqual(original_variant.product_tmpl_id.id, product_template.id,
                        "Variant should be linked to template")

        # Update the product (simulate re-sync)
        shopify_product['variants'][0]['price'] = '129.99'
        self.shopify_sync._save_single_product(shopify_product)

        # Refresh records
        original_variant.invalidate_recordset()

        # Verify linkage is preserved and price is updated
        self.assertEqual(original_variant.product_tmpl_id.id, product_template.id,
                        "Variant linkage should be preserved after update")
        self.assertEqual(original_variant.list_price, 129.99,
                        "Variant price should be updated")
