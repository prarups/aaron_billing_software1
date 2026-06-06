# Aaron Billing Software - Manual Testing & Requirements Guide

This document defines the page-based and role-based requirements for the Aaron Billing system, along with step-by-step instructions for manual testing.

---

## Part 1: Role-Based Requirements Matrix

| Feature / Page | Admin (Owner) | Manager (With Rights) | Manager (No Rights) | Staff |
| :--- | :---: | :---: | :---: | :---: |
| **Admin Dashboard** | Full Access | No Access | No Access | No Access |
| **All Branches Tab** | CRUD | No Access | No Access | No Access |
| **Staff & Assigning Tab** | Manage & Toggle | No Access | No Access | No Access |
| **Product Master (View)** | Yes | Yes | Yes | No Access (302 Redirect) |
| **Product CRUD / Bulk Insert** | Yes | Yes | No Access (302 Redirect) | No Access (302 Redirect) |
| **Inline Price / Stock Edit** | Yes | Yes | No / Read-only | No Access |
| **Multi-Branch Stock Report** | Yes | Yes | Yes | No Access |
| **Reconciliation / Correction** | Yes | Yes | No / Hidden | No Access |
| **POS Billing Page** | Yes | Yes | Yes | Yes (Active branch only) |
| **Sales / Returns Report** | Yes | Yes | Yes | No Access |

---

## Part 2: Page-by-Page Requirements & Test Steps

### 1. Login Page
#### Requirements:
- Users must select their correct role (Admin, Manager, Staff).
- Managers and Staff must select a branch from the dropdown. Owners (Admins) do not need to select a branch.
- Deactivated accounts must be blocked with an warning message.

#### Test Steps:
1. Try to log in with `username: admin`, `password: admin123` selecting **Admin** role (leave branch empty).
   * *Expected Result*: Success. Redirects to Admin Dashboard.
2. Log out. Try to log in with `admin` but select **Manager** or **Staff**.
   * *Expected Result*: Fails with validation error: *"You do not have the required permissions for this role."*
3. Log in as a deactivated account.
   * *Expected Result*: Fails with error: *"Your account is inactive. Please contact admin team."*

---

### 2. Admin Dashboard
#### Overview Tab:
- **Requirements**: Shows business metrics, total sales today, active branches count, low stock alerts, branch performance list, recent sales list, and a "Export CSV" sales report download.
- **Test Steps**:
  1. Access the dashboard as Admin.
  2. Click "Export CSV" at the top of the card. Verify a CSV file containing sales is downloaded.

#### All Branches Tab:
- **Requirements**: Lists all branches with Code, Name, Location, Contact, and Prefix.
- **Test Steps**:
  1. Click "Create New Branch". Enter name, location, and prefix (e.g. prefix `NY`, code auto-assigned). Save and verify.
  2. Click the pencil icon to edit branch details. Save and verify.
  3. Click the trash icon to delete. Confirm delete and verify.

#### Staff & Assigning Tab:
- **Requirements**:
  - List of employees with columns: Employee ID, Username, Full Name, Role, Status (toggle), Product edit rights (toggle for managers), Assigned Branches, Actions.
  - Search/Filter by Branch and Role dropdowns.
  - Toggle status to deactivate/activate staff accounts.
  - Owners cannot deactivate themselves.
  - Toggle product rights to grant/revoke edit permissions for managers.
- **Test Steps**:
  1. **Add Staff**: Click "Add Staff". Input details. Leave Employee ID blank. Assign multiple branches. Save. Verify that Employee ID auto-generates starting with the branch prefix (e.g., `NY0001` or fallback `AR0001`).
  2. **Edit Staff**: Click edit icon, change password. Save. Log out and verify you can log in with the new password. Ensure the account remains Active.
  3. **Filter Staff**: Select a branch from the dropdown. Select "Manager" role. Verify only matching staff are shown.
  4. **Self-Deactivation Check**: Locate your own row in the table. Verify the Status toggle switch is **disabled** with tooltip: *"You cannot deactivate your own account"*.
  5. **Product Rights Check**: Toggle "Product edit rights" ON/OFF for a manager user. Verify state is saved. Verify that Staff and Admins show `-` in this column.

---

### 3. Product Master
#### Requirements:
- View product names, barcodes, prices, combos, and stock levels.
- Add Product, Edit Product, Bulk Insert actions.
- Inline edit product price or stock.
- Restricted to Admins and Managers with "Product edit rights".

#### Test Steps:
1. **Logged in as Admin or Manager with Product Rights**:
   - Go to `/core/products/`. Verify the "Add New" and "Bulk Insert" buttons are visible.
   - Click "Add New", enter details (combo price, barcode). Save.
   - Click a product's price or stock in the table. Enter a new number. Verify it saves dynamically without page reload.
   - Click "Bulk Insert", download the CSV template, fill in products, upload, and verify bulk creation.
2. **Logged in as Manager WITHOUT Product Rights**:
   - Go to `/core/products/`. Verify "Add New" and "Bulk Insert" buttons are **hidden**.
   - Verify that clicking on prices/stock in the table does **not** trigger editing mode (read-only).
   - Manually enter `/core/products/add/` in the URL. Verify redirect back to `/core/products/` with error: *"Permission denied. You do not have product edit rights."*

---

### 4. Multi-Branch Stock Report
#### Requirements:
- Show stock details (Op, In, Out, Dmg, Cl) aggregated and per branch.
- Stock correction / damage logging (reconciliation tool).
- Restricted to Admin and Managers with rights.

#### Test Steps:
1. Expand a product row in the table.
2. **As Admin / Manager with rights**:
   - Verify the wrench icon `Correct` is visible.
   - Click it to access `/core/products/adjust-stock/<id>/`.
   - Enter correction amount (e.g. `-2` for damage, with reason). Save and verify closing stock updates correctly.
3. **As Manager without rights**:
   - Expand a row. Verify the wrench icon is **hidden**.
   - Access the URL manually. Verify redirection to product list with permission error.

---

### 5. Sales & Return Report
#### Requirements:
- List all bills, customer names, billing amounts.
- Filter by date, branch, and payment method.
- Return request creation.

#### Test Steps:
1. Go to Sales Report. Use the filters to narrow down transactions.
2. Click "Return Request" next to a bill item.
3. Input return quantity, reason, and process. Verify stock ledger updates (OUT becomes IN/returned).

---

### 6. POS Billing Page
#### Requirements:
- POS grid layout loaded with products from active branch.
- Search/add items to cart.
- Discount support (percentage or absolute amount).
- Split payment options (Cash + Online payments).
- Print receipt layout.

#### Test Steps:
1. Log in as Staff/Manager/Admin. Go to POS.
2. Search a product by barcode or name. Click to add to cart.
3. Apply a discount of 10%. Verify total updates.
4. Select payment method: **Split**. Enter Cash portion (e.g., 100) and Online portion (e.g., remaining).
5. Click "Submit Bill". Verify success and that invoice print preview opens.
