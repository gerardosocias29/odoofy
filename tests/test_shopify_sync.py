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
