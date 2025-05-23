# INSTRUCTIONS.md

## 🧠 Agent AI: Odoo-Shopify Bi-directional Integration

This Odoo addon enables **bi-directional synchronization** between **Shopify** and **Odoo**, keeping product catalog, inventory, vendors, orders, and **product categories** in sync. Each task should be implemented as a one-time callable method to support CRON automation.

---

## 🔁 Integration Overview

### ✅ Shopify ➝ Odoo

Automatically imports:

* Products (created in the current year)
* Variants
* Product images
* Inventory levels
* Vendors
* **Product Categories** (Shopify "Product Type" mapped to Odoo Category)
* **Dropship enabled by default** if product has a vendor

### ✅ Odoo ➝ Shopify

Automatically exports:

* Products & variants
* Inventory adjustments
* Vendor assignments

### ✅ Shopify Orders ➝ Odoo

Automatically imports:

* Orders placed in Shopify
* Customers, items, shipping mapped to Odoo Sales Orders

---

## 🔧 Development Guidelines

### 1. **Environment Configuration**

Use `ir.config_parameter` to fetch configuration and sync state:

```python
shopify_access_token = self.env['ir.config_parameter'].sudo().get_param('shopify.access_token')
shopify_store_url = self.env['ir.config_parameter'].sudo().get_param('shopify.store_url')
next_page = self.env['ir.config_parameter'].sudo().get_param('shopify.next_page')
```

---

## 🔄 Product Sync Logic

### Method: `auto_sync_shopify_products()`

```python
def auto_sync_shopify_products(self):
    ...
    if not next_page:
        products, next_page_token = self.fetch_shopify_products(limit=10, created_this_year=True)
        self.env['ir.config_parameter'].sudo().set_param('shopify.next_page', next_page_token)
        self.save_products_to_odoo(products)
    else:
        products, next_page_token = self.fetch_shopify_products(limit=10, page_info=next_page)
        self.env['ir.config_parameter'].sudo().set_param('shopify.next_page', next_page_token)
        self.save_products_to_odoo(products)
```

---

### Method: `fetch_shopify_products()`

```python
def fetch_shopify_products(self, limit=10, page_info=None, created_this_year=False):
    ...
```

---

### Method: `save_products_to_odoo(products)`

* Extracts:

  * Product info
  * Variants
  * Images
  * **Product Type ➝ Odoo Category**
  * **Vendor ➝ res.partner**
  * **Enables Dropshipping if vendor exists**

```python
def save_products_to_odoo(self, products):
    for product in products:
        # Handle Category
        category_name = product.get('product_type') or 'Uncategorized'
        category = self.env['product.category'].sudo().search([('name', '=', category_name)], limit=1)
        if not category:
            category = self.env['product.category'].sudo().create({'name': category_name})

        product_vals = {
            'name': product['title'],
            'categ_id': category.id,
            ...
        }

        # Handle Vendor and Dropshipping
        if product.get('vendor'):
            vendor = self.env['res.partner'].sudo().search([('name', '=', product['vendor'])], limit=1)
            if not vendor:
                vendor = self.env['res.partner'].sudo().create({'name': product['vendor'], 'supplier_rank': 1})

            product_vals['seller_ids'] = [(0, 0, {
                'name': vendor.id,
                'min_qty': 1,
                'price': 0.0,
            })]

            # Enable dropshipping
            dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping')
            if dropship_route:
                product_vals['route_ids'] = [(6, 0, [dropship_route.id])]

        # Create or update product
        ...
```

---

## 🧩 Model Mappings

| Shopify Field | Odoo Model         | Notes                      |
| ------------- | ------------------ | -------------------------- |
| Product       | `product.template` | Main product               |
| Variant       | `product.product`  | Linked to product template |
| Vendor        | `res.partner`      | Supplier                   |
| Product Type  | `product.category` | Category in Odoo           |
| Order         | `sale.order`       | Shopify order → Odoo SO    |

---

## ✅ CRON Job Example

```xml
<record id="ir_cron_auto_sync_shopify_products" model="ir.cron">
    <field name="name">Auto Sync Shopify Products</field>
    <field name="model_id" ref="model_shopify_sync"/>
    <field name="state">code</field>
    <field name="code">model.auto_sync_shopify_products()</field>
    <field name="interval_number">1</field>
    <field name="interval_type">hours</field>
    <field name="numbercall">-1</field>
    <field name="active">True</field>
</record>
```

---

## 🔄 Pagination Logic

```python
def parse_next_page_token(self, link_header):
    if not link_header:
        return None
    match = re.search(r'page_info=([^&>]+)', link_header)
    return match.group(1) if match else None
```