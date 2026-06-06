# Aaron Billing Software - Complete Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Technology Stack](#technology-stack)
3. [Database Models](#database-models)
4. [Application Modules](#application-modules)
5. [User Roles & Permissions](#user-roles--permissions)
6. [API Endpoints](#api-endpoints)
7. [Key Features](#key-features)
8. [Workflows](#workflows)
9. [Data Flow](#data-flow)
10. [Setup & Deployment](#setup--deployment)

---

## 1. Project Overview

**Aaron Billing** is a high-performance, multi-branch POS (Point of Sale) and Inventory Management System built with Django. It features a "Vibrant Premium" UI design with glassmorphism and micro-animations.

### Key Capabilities:
- **Multi-Branch Management**: Seamlessly switch between branches with role-based access
- **Intelligent Inventory**: Global product registry with branch-specific stock levels
- **Advanced POS**: Real-time cart, barcode scanner (webcam-based), AJAX product lookup
- **Digital Receipts**: Unique sharing IDs, WhatsApp integration, public receipt view
- **Comprehensive Reporting**: Daily staff activity, multi-branch sales reports, CSV export

---

## 2. Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Django 6.0 (Python) |
| Database | PostgreSQL (Production) / SQLite (Local) |
| Frontend | Bootstrap 5, Vanilla JS, Google Fonts (Inter) |
| Deployment | Railway (gunicorn + whitenoise) |
| Additional | REST Framework, openpyxl (Excel export) |

---

## 3. Database Models

### Core App Models (`core/models.py`)

#### Branch
```python
- name: CharField(100)
- location: CharField(255)
- contact_number: CharField(20)
- created_at: DateTime (auto)
```
Represents a business location/branch.

#### Product
```python
- name: CharField(200)
- barcode: CharField(50) - unique, indexed
- price: DecimalField(10,2)
- branches: ManyToManyField (via ProductRegistry)
- created_at, updated_at: DateTime (auto)
```
Global product catalog - same product can exist in multiple branches.

#### ProductRegistry (Through Model)
```python
- branch: ForeignKey -> Branch
- product: ForeignKey -> Product
- stock_quantity: Integer (default=0)
- low_stock_threshold: Integer (default=10)
- created_at, updated_at: DateTime (auto)
```
**Purpose**: Branch-specific stock level for each product. Each product-branch combination has its own inventory.

#### StockTransaction
```python
- product: ForeignKey -> Product
- branch: ForeignKey -> Branch
- transaction_type: CharField choices=(IN, OUT, ADJ)
- quantity: Integer
- reference: CharField (e.g., "Bill #123", "Initial Stock")
- user: ForeignKey -> User
- created_at: DateTime (auto)
```
**Purpose**: Audit trail of all stock movements.

#### StockAdjustment
```python
- product, branch: ForeignKey
- opening_balance: Integer
- stock_in, stock_out: Integer
- correction_amount: Integer (positive=add, negative=subtract)
- closing_stock: Integer
- is_in_stock: Boolean
- reason: CharField(255)
- user: ForeignKey
- created_at: DateTime
```
**Purpose**: Audit trail for wrong-entry corrections using reconciliation logic.

---

### Billing App Models (`billing/models.py`)

#### Bill
```python
- branch: ForeignKey -> Branch
- staff: ForeignKey -> User
- customer_name, customer_phone: CharField
- total_amount: DecimalField(12,2)
- discount_amount: DecimalField(12,2)
- cash_amount, online_amount: DecimalField
- payment_method: CharField choices=(cash, online, split)
- share_id: UUID (auto-generated, unique)
- created_at: DateTime (auto)
```

#### BillItem
```python
- bill: ForeignKey -> Bill
- product: ForeignKey -> Product
- quantity: PositiveInteger
- unit_price: DecimalField
- subtotal: DecimalField (computed: quantity * unit_price)
```

---

### Users App Models (`users/models.py`)

#### User (Custom AbstractUser)
```python
- role: CharField choices=(owner, manager, staff)
- branches: ManyToManyField -> Branch (for managers/staff)
- active_branch: ForeignKey -> Branch (session-specific)
```

**User Methods**:
- `is_owner()` - returns True if role='owner'
- `is_manager()` - returns True if role='manager'
- `is_staff_role()` - returns True if role='staff'
- `get_accessible_branches()` - returns all branches (owner) or assigned branches

---

## 4. Application Modules

### Users App (`users/`)
| File | Description |
|------|-------------|
| `models.py` | Custom User model with role-based access |
| `views.py` | Dashboard views (Owner, Manager, Staff), branch switching |
| `urls.py` | Authentication and dashboard routes |
| `forms.py` | Custom authentication form |

**URL Routes**:
- `/users/login/` - Login page
- `/users/logout/` - Logout
- `/users/dashboard/` - Role-based dashboard redirect
- `/users/dashboard/owner/` - Owner dashboard
- `/users/dashboard/manager/` - Manager dashboard
- `/users/dashboard/staff/` - Staff dashboard
- `/users/switch-branch/` - Switch active branch (POST)

---

### Core App (`core/`)
| File | Description |
|------|-------------|
| `models.py` | Branch, Product, ProductRegistry, StockTransaction, StockAdjustment |
| `views.py` | Product management, stock reports, bulk operations |
| `urls.py` | Product and report routes |

**URL Routes**:
- `/core/products/` - Product list with filters
- `/core/products/add/` - Create new product
- `/core/products/edit/<pk>/` - Edit product
- `/core/products/export/` - Export products CSV
- `/core/products/bulk-insert/` - Bulk import via CSV
- `/core/products/bulk-template/` - Download CSV template
- `/core/products/adjust-stock/<reg_id>/` - Stock correction
- `/core/reports/stock-pivot/` - Multi-branch stock report
- `/core/reports/stock-pivot/export/` - Export to Excel

---

### Billing App (`billing/`)
| File | Description |
|------|-------------|
| `models.py` | Bill, BillItem |
| `views.py` | POS, bill processing, reports |
| `urls.py` | Billing routes |

**URL Routes**:
- `/billing/` - POS interface
- `/billing/get-product/` - AJAX product lookup by barcode
- `/billing/process-bill/` - Process new bill (POST)
- `/billing/bill/<id>/` - Bill detail view
- `/billing/bill/<id>/update-customer/` - Update customer details (POST)
- `/billing/share/<uuid>/` - Public bill receipt (no login required)
- `/billing/activity/` - Staff daily activity
- `/billing/all-bills/` - Owner/Manager bill list
- `/billing/export/` - Export sales CSV

---

## 5. User Roles & Permissions

| Role | Permissions |
|------|-------------|
| **Owner** | Full access to all branches, all bills, all reports, product management, user management |
| **Manager** | Access to assigned branches only, manage products/stock in assigned branches, view branch bills |
| **Staff** | POS access only, can only see their own bills, cannot access product management or reports |

### Branch Access Logic
```python
# In User model
def get_accessible_branches(self):
    if self.is_owner():
        return Branch.objects.all()
    return self.branches.all()  # Only assigned branches
```

### Active Branch
- Managers/Staff can only work in one branch at a time (stored in `active_branch`)
- Can switch branches via `/users/switch-branch/`
- All stock operations and bills are tied to the active branch

---

## 6. API Endpoints

### Public Endpoints
| Method | URL | Description |
|--------|-----|-------------|
| GET | `/billing/share/<uuid>/` | View public bill receipt |

### Authenticated Endpoints (AJAX/API)

#### Product Lookup
- **GET** `/billing/get-product/?barcode=XYZ`
  - Returns: `{id, name, price, stock}`

#### Bill Processing
- **POST** `/billing/process-bill/`
  - Body: `{items: [], customer_name, customer_phone, payment_method, cash_amount, online_amount, discount_amount}`
  - Returns: `{success: true, bill_id: int}`

#### Stock Update (AJAX)
- **POST** `/core/products/update-stock-ajax/<reg_id>/`
  - Body: `{stock: int}`
- **POST** `/core/products/update-price-ajax/<product_id>/`
  - Body: `{price: float}`

#### Customer Update
- **POST** `/billing/bill/<bill_id>/update-customer/`
  - Body: `{customer_name, customer_phone}`

---

## 7. Key Features

### 7.1 Multi-Branch Inventory System
- **Global Products**: One product can exist in multiple branches
- **Branch-Specific Stock**: Each branch has independent inventory
- **Low Stock Alerts**: Configurable threshold per product-branch combination

### 7.2 Point of Sale (POS)
- Real-time cart management
- Webcam-based barcode scanning
- AJAX product lookup
- Support for cash, online, and split payments
- Automatic stock deduction on bill creation

### 7.3 Stock Management
- **Stock Transactions**: Tracks IN (stock in), OUT (sales), ADJ (adjustment)
- **Stock Adjustment**: Reconciliation-based correction with audit trail
- **Formula**: `Closing Stock = Opening Balance + Stock In - Stock Out + Correction`

### 7.4 Billing Features
- Unique shareable bill URLs (UUID)
- Public receipt view for customers
- WhatsApp integration for sending receipts
- Discount support per bill
- Payment method tracking (cash/online/split)

### 7.5 Reporting
- **Stock Pivot Report**: Opening, In, Out, Closing per product per branch
- **Staff Activity**: Daily sales and items sold per staff
- **Sales Reports**: Filter by date, branch, payment method
- **Export Options**: CSV and Excel formats

### 7.6 Bulk Operations
- CSV-based bulk product import
- Template download for bulk import
- Updates existing products on barcode match

---

## 8. Workflows

### 8.1 Creating a New Bill (POS Flow)
```
1. Staff logs in -> redirected to POS (role=staff restricted)
2. Staff scans barcode or searches product
3. AJAX looks up product + current stock for active branch
4. Staff adds items to cart
5. Staff enters customer info (optional), selects payment method
6. Submit bill -> process_bill view:
   - Creates Bill record
   - For each item:
     - Checks stock availability
     - Decrements stock_quantity in ProductRegistry
     - Creates BillItem
     - Creates StockTransaction (type=OUT)
   - Updates total_amount
7. Returns bill_id -> shows receipt
8. Receipt can be shared via unique URL or WhatsApp
```

### 8.2 Stock Correction Flow
```
1. Manager/Owner navigates to Stock Pivot Report
2. Clicks "Adjust" on a product-branch combination
3. stock_adjustment view shows:
   - Opening balance (calculated: current_stock - today_in + today_out)
   - Today's stock in/out
   - Current closing stock
4. Enter correction_amount (positive/negative)
5. System validates: new_closing >= 0
6. On submit:
   - Updates ProductRegistry.stock_quantity
   - Creates StockAdjustment (audit record)
   - Creates StockTransaction (type=ADJ)
7. Redirects back to report
```

### 8.3 Bulk Product Import Flow
```
1. Manager/Owner downloads template (download_bulk_template)
2. Fills CSV: Branch, Product Name, Barcode, Price, Stock, Low Stock Level
3. Uploads CSV in bulk_insert view
4. For each row:
   - Finds/creates Branch
   - Finds/creates Product (by barcode)
   - Creates/updates ProductRegistry
   - Creates StockTransaction if stock changed
5. Returns summary: success_count, error_count, errors[]
```

---

## 9. Data Flow

### Stock Movement Flow
```
Initial Stock (IN):
  ProductRegistry.stock_quantity += quantity
  StockTransaction(type=IN, quantity, reference="Initial Stock")

Sale (OUT):
  ProductRegistry.stock_quantity -= quantity
  StockTransaction(type=OUT, quantity, reference="Bill #X")

Manual Adjustment (ADJ):
  ProductRegistry.stock_quantity += correction
  StockTransaction(type=ADJ, quantity, reference="Correction: reason")
  StockAdjustment created (audit)
```

### Role-Based Dashboard Flow
```
Login -> dashboard_redirect
  -> if owner: owner_dashboard (all branches, all reports)
  -> if manager: manager_dashboard (assigned branches)
  -> if staff: staff_dashboard (POS only, own bills)
```

---

## 10. Setup & Deployment

### Local Development
```bash
# Clone and install dependencies
git clone <repo-url>
cd aaron_billing_software
pip install -r requirements.txt

# Set environment variables (or edit settings.py)
export DEBUG=True
export SECRET_KEY='your-secret-key'

# Migrate database
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run server
python manage.py runserver
```

### Production (Railway)
1. Set environment variables in Railway dashboard:
   - `DATABASE_URL` (PostgreSQL)
   - `SECRET_KEY`
   - `DEBUG=False`
   - `RAILWAY_PUBLIC_DOMAIN`
2. Procfile configured for gunicorn
3. whitenoise for static files

### Key Configuration (settings.py)
- `AUTH_USER_MODEL = 'users.User'` - Custom user model
- `TIME_ZONE = 'Asia/Kolkata'` - IST timezone
- `ALLOWED_HOSTS = ['*']` (configured for Railway)
- Static files: STATIC_ROOT, STATICFILES_DIRS
- Media files: MEDIA_ROOT, MEDIA_URL

---

## File Structure Summary

```
aaron_billing_software/
├── config/
│   ├── settings.py      # Django settings
│   ├── urls.py          # Root URL config
│   ├── wsgi.py          # WSGI application
│   └── asgi.py          # ASGI application
├── users/
│   ├── models.py        # Custom User model
│   ├── views.py        # Dashboard views
│   └── urls.py         # Auth & dashboard routes
├── core/
│   ├── models.py        # Branch, Product, ProductRegistry, StockTransaction
│   ├── views.py        # Product management, stock reports
│   └── urls.py         # Product & report routes
├── billing/
│   ├── models.py        # Bill, BillItem
│   ├── views.py        # POS, bill processing, reports
│   └── urls.py         # Billing routes
├── templates/           # HTML templates
├── static/             # CSS, JS
├── manage.py
└── requirements.txt
```

---

## Security Considerations

- CSRF protection enabled
- X-Frame-Options: DENY (prevents clickjacking)
- Session cookies secure in production
- SSL redirect in production
- Role-based access control in all views
- Staff users cannot access management features

---

*Documentation generated for Aaron Billing Software*