# System Architecture: Aaron Billing 🏗️

Aaron Billing is a robust, multi-tenant (multi-branch) billing and inventory system designed for efficiency and modern aesthetics.

## 📁 Directory Structure
```text
f:/antigravity/aaron_billing_software
├── billing/             # Transactional Sales & POS Logic
├── config/              # Django Settings & Global URL Routing
├── core/                # Shared Models (Branch, Product)
├── inventory/           # Stock Tracking & Management
├── users/               # Custom User Models & Role-Based Access
├── templates/           # HTML5/Django Boilerplates
├── static/              # CSS/JS (Vibrant Premium Branding)
└── requirements.txt     # Python Dependencies
```

## 🗄️ Core Data Models

### 1. User & Authentication (`users/`)
- **Custom User Model**: Extends `AbstractUser`.
- **Roles**:
  - `owner`: Full access to all branches and reporting.
  - `manager`: Assigned to specific branches, can manage inventory and view branch reports.
  - `staff`: Point of Sale access for assigned branches only.
- **Active Branch**: Every user session tracks an `active_branch` to filter all business data.

### 2. Physical & Product Structure (`core/`)
- **Branch**: Represents a storefront or warehouse (Name, Location, Contact).
- **Product**: Global registry of items (Name, Barcode, Base Price).

### 3. Inventory (`inventory/`)
- **Inventory Model**: A bridge between `Branch` and `Product`.
- **Fields**: `stock_quantity`, `low_stock_threshold`.
- **Feature**: Stock is deducted automatically when a POS transaction is completed.

### 4. Billing & Sales (`billing/`)
- **Bill**: Records the header of a transaction (Branch, Staff, Customer, Total, Payment Method).
- **BillItem**: Records individual line items for each bill.
- **Public Share ID**: A unique UUID is generated for every bill, allowing for secure, login-free web viewing by customers.

## 🛡️ Business Logic & Permissions
- **Branch-Switching**: Owners can switch branches dynamically via the sidebar. Data throughout the app (Inventory, Products, Sales) is filtered by the session's `active_branch`.
- **POS Security**: POS operations are atomic. We use database transactions with `select_for_update()` to prevent race conditions during heavy billing (e.g., two staff members selling the same last item simultaneously).
- **Receipt Sharing**: Integration with WhatsApp via dynamically generated URLs.

## 🎨 Design System: "Vibrant Premium"
The UI is built on **Bootstrap 5** with intensive CSS customization (`static/css/style.css`):
- **Glassmorphism**: Cards and navigation bars feature translucent backdrops with subtle borders.
- **Vibrant Palette**: Uses deep indigos and lightning accents for a high-energy, professional feel.
- **Haptic/Micro-Interactions**: POS items scale slightly on hover/click, and success states are visually reinforced.

## ☁️ Deployment Architecture
- **Web Server**: `Gunicorn` handles concurrent requests.
- **Static Assets**: `WhiteNoise` serves static files directly from Django for high-speed, CDN-like performance.
- **Infrastructure**: Configured for Railway's ephemeral file system with PostgreSQL for persistent data.
