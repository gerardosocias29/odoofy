#!/usr/bin/env python3
"""
Script to clean Shopify sync data from Odoo database
Run this script to reset all Shopify-related data and start fresh
"""

import psycopg2
import sys

def clean_shopify_data():
    """Clean all Shopify-related data from the database"""
    
    # Database connection parameters - UPDATE THESE FOR YOUR SETUP
    DB_CONFIG = {
        'host': 'localhost',
        'database': 'odoo',  # Replace with your database name
        'user': 'odoo',      # Replace with your database user
        'password': 'odoo',  # Replace with your database password
        'port': 5432
    }
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("🧹 Starting Shopify data cleanup...")
        
        # 1. Delete Shopify products (products with SHOPIFY_ prefix)
        print("Deleting Shopify products...")
        cursor.execute("""
            DELETE FROM product_product 
            WHERE default_code LIKE 'SHOPIFY_%'
        """)
        deleted_variants = cursor.rowcount
        print(f"   ✅ Deleted {deleted_variants} product variants")
        
        cursor.execute("""
            DELETE FROM product_template 
            WHERE default_code LIKE 'SHOPIFY_%'
        """)
        deleted_products = cursor.rowcount
        print(f"   ✅ Deleted {deleted_products} product templates")
        
        # 2. Delete Shopify orders
        print("Deleting Shopify orders...")
        cursor.execute("""
            DELETE FROM sale_order 
            WHERE client_order_ref LIKE 'SHOPIFY_%'
        """)
        deleted_orders = cursor.rowcount
        print(f"   ✅ Deleted {deleted_orders} orders")
        
        # 3. Delete Shopify sync records
        print("Deleting sync records...")
        cursor.execute("DELETE FROM shopify_sync")
        deleted_sync_records = cursor.rowcount
        print(f"   ✅ Deleted {deleted_sync_records} sync records")
        
        # 4. Reset Shopify configuration parameters
        print("Resetting Shopify configuration...")
        shopify_params = [
            'shopify.last_updated_at',
            'shopify.orders_last_updated_at',
            'shopify.total_products_count',
            'shopify.total_orders_count',
            'shopify.last_odoo_to_shopify_sync'
        ]
        
        for param in shopify_params:
            cursor.execute("""
                UPDATE ir_config_parameter 
                SET value = '' 
                WHERE key = %s
            """, (param,))
        
        print(f"   ✅ Reset {len(shopify_params)} configuration parameters")
        
        # 5. Delete Shopify-related attachments/images (optional)
        print("Cleaning up Shopify attachments...")
        cursor.execute("""
            DELETE FROM ir_attachment 
            WHERE name LIKE '%shopify%' OR name LIKE '%SHOPIFY%'
        """)
        deleted_attachments = cursor.rowcount
        print(f"   ✅ Deleted {deleted_attachments} attachments")
        
        # Commit all changes
        conn.commit()
        
        print("\n🎉 Shopify data cleanup completed successfully!")
        print(f"Summary:")
        print(f"  - Products deleted: {deleted_products}")
        print(f"  - Variants deleted: {deleted_variants}")
        print(f"  - Orders deleted: {deleted_orders}")
        print(f"  - Sync records deleted: {deleted_sync_records}")
        print(f"  - Attachments deleted: {deleted_attachments}")
        print(f"  - Config parameters reset: {len(shopify_params)}")
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    print("⚠️  WARNING: This will delete ALL Shopify-related data!")
    print("   - All Shopify products and variants")
    print("   - All Shopify orders")
    print("   - All sync records and timestamps")
    print("   - Shopify-related attachments")
    print()
    
    response = input("Are you sure you want to continue? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        clean_shopify_data()
    else:
        print("❌ Cleanup cancelled")
