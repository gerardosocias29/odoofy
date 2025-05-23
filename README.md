# Odoo-Shopify Integration

This Odoo addon provides bi-directional synchronization between Shopify and Odoo, enabling seamless integration of product catalogs, inventory, orders, and customer data.

## Features

### Shopify → Odoo Synchronization
- **Products & Variants**: Import products with all variants from Shopify
- **Product Images**: Download and attach product images
- **Inventory Levels**: Sync inventory quantities
- **Vendors**: Create vendor records from Shopify vendor data
- **Product Categories**: Map Shopify "Product Type" to Odoo Categories
- **Dropshipping**: Automatically enable dropshipping for products with vendors
- **Orders**: Import Shopify orders as Odoo Sales Orders
- **Customers**: Create customer records from order data

### Odoo → Shopify Synchronization
- **Product Export**: Export new Odoo products to Shopify
- **Product Updates**: Update existing Shopify products with Odoo changes
- **Inventory Sync**: Real-time inventory level synchronization
- **Variant Updates**: Sync product variant changes (price, weight, barcode)
- **Vendor Assignments**: Include vendor information in exports

### Key Features
- **Pagination Support**: Handle large datasets efficiently
- **CRON Automation**: Automated synchronization jobs
- **Timestamp-based Sync**: Only sync products modified since last update
- **Error Handling**: Comprehensive logging and error management
- **Configuration Management**: Easy setup via Odoo Settings
- **Duplicate Prevention**: Intelligent handling of existing records

## Installation

1. Copy the `odoofy` folder to your Odoo addons directory
2. Update the addons list in Odoo
3. Install the "Odoo-Shopify Integration" module

**Note**: This addon requires the `stock_dropshipping` module for automatic dropshipping functionality. It will be installed automatically as a dependency.

## Configuration

1. Go to **Settings → General Settings**
2. Find the **Shopify Integration** section
3. Configure the following:
   - **Shopify Access Token**: Your private app access token
   - **Shopify Store URL**: Your store URL (e.g., https://your-store.myshopify.com)
   - **API Version**: Shopify API version (default: 2023-10)
4. Test the connection using the "Test Connection" button
5. Enable automatic synchronization options as needed

## Usage

### Manual Synchronization
1. Go to **Shopify Integration → Synchronization**
2. Create a new sync record
3. Use the buttons to:
   - **Sync Products from Shopify**: Import products from Shopify to Odoo
   - **Sync Orders from Shopify**: Import orders from Shopify to Odoo
   - **Export Products to Shopify**: Export new Odoo products to Shopify
   - **Sync Inventory to Shopify**: Update inventory levels in Shopify
   - **Update Products in Shopify**: Update existing Shopify products with Odoo changes

### Automatic Synchronization
Enable CRON jobs in **Settings → Technical → Automation → Scheduled Actions**:
- **Auto Sync Shopify Products**: Import products from Shopify (every hour)
- **Auto Sync Shopify Orders**: Import orders from Shopify (every 30 minutes)
- **Export Products to Shopify**: Export new products to Shopify (every 2 hours)
- **Sync Inventory to Shopify**: Update inventory levels in Shopify (every hour)
- **Update Products in Shopify**: Update existing products in Shopify (every 4 hours)

## Data Mapping

| Shopify Field | Odoo Model | Odoo Field | Notes |
|---------------|------------|------------|-------|
| Product | product.template | name, default_code | |
| Variant | product.product | name, default_code, list_price | |
| Vendor | res.partner | name, supplier_rank | Enables dropshipping route |
| Product Type | product.category | name | |
| Order | sale.order | client_order_ref, origin | |
| Customer | res.partner | name, email, customer_rank | |

## Technical Details

### Models
- `shopify.sync`: Main synchronization model
- `res.config.settings`: Configuration settings extension

### Security
- **Shopify Sync User**: Read-only access to sync records
- **Shopify Sync Manager**: Full access to sync operations

### API Integration
- Uses Shopify Admin REST API
- Supports pagination for large datasets
- Implements proper error handling and retry logic

### Timestamp-based Synchronization
- **Smart Updates**: Only syncs products modified since last synchronization
- **Conflict Prevention**: Compares Odoo `write_date` with Shopify `updated_at`
- **Efficient Processing**: Reduces API calls and processing time
- **Timestamp Tracking**: Stores sync timestamps on product records

## Troubleshooting

### Common Issues
1. **Connection Failed**: Check access token and store URL
2. **Products Not Syncing**: Verify API permissions
3. **Orders Missing**: Check order status filters
4. **Images Not Loading**: Verify image URLs and network access

### Logs
Check sync logs in the synchronization records for detailed error information.

## Support

For issues and feature requests, please refer to the Odoo community forums or create an issue in the project repository.

## License

This addon is licensed under LGPL-3.
