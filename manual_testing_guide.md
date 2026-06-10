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
- Users log in using only their **Username** (or **Employee ID**) and **Password**.
- The role and branch assignment are determined automatically based on the user account configuration.
- Deactivated accounts must be blocked with an warning message.
- Fullscreen glassmorphic design layout.

#### Test Steps:
1. Log in with `username: admin` and `password: admin123`.
   * *Expected Result*: Success. Redirects to Owner Dashboard.
2. Log out. Log in using the **Employee ID** of an active staff member (e.g. `AN0001`) and their password.
   * *Expected Result*: Success. Redirects to Staff Dashboard (POS) and automatically selects their active branch.
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
  - **Mobile Number** (mandatory) and **Address** (optional) fields are required when adding or editing staff.
- **Test Steps**:
  - **Add Staff**: 
    1. Click "Add Staff". Leave the "Mobile Number" field empty and click save.
       * *Expected Result*: Browser form validation prevents submission, showing a warning that Mobile Number is required.
    2. Input a valid Mobile Number (e.g. `9876543210`), fill in other details, leave Employee ID blank, leave Address blank, and save.
       * *Expected Result*: Success. Employee ID is auto-generated and account is created without an address.
    3. Click "Add Staff" again, fill all fields including an Address (e.g. `123 Main St`), and save.
       * *Expected Result*: Success. Account is created with the specified address.
  - **Edit Staff**: Click the edit pencil icon for a staff member. Verify that their existing Mobile Number and Address are pre-populated in the modal. Change the values and save. Verify that the updated values are correctly stored and shown when reopening the modal.
  - **Filter Staff**: Select a branch from the dropdown. Select "Manager" role. Verify only matching staff are shown.
  - **Self-Deactivation Check**: Locate your own row in the table. Verify the Status toggle switch is **disabled** with tooltip: *"You cannot deactivate your own account"*.
  - **Product Rights Check**: Toggle "Product edit rights" ON/OFF for a manager user. Verify state is saved. Verify that Staff and Admins show `-` in this column.

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
   - Click "Bulk Insert", download the CSV template.
   - Fill in one row with a test product, e.g., product name: `T-Shirt`, barcode: `TSHIRT99`, price: `150`, initial stock: `20`, branch code: `10001` (or matching active branch code). Save and upload this CSV.
   - Go back to `/core/products/` and verify that the product has been created with stock = 20.
   - Prepare another CSV (or modify the same CSV) with the exact same barcode `TSHIRT99` but set the initial stock to `15`. Upload the file again.
   - Verify that the total stock for this product is now **35** (20 + 15), meaning the stock accumulated rather than being overwritten. Check the Multi-Branch Stock Report to confirm a `Bulk Update` transaction of type `IN` with quantity `15` has been recorded.
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

---

### 7. PWA Installation (Install App Button)
#### Requirements:
- The dashboard navbar displays an "Install App" button on supported browsers when the PWA is installable.
- The button is hidden if the app is already installed or if the browser does not support PWA installation.
- Clicking the button prompts the native browser install dialog.
- The button disappears automatically once installation completes.

#### Test Steps:
1. Access the web application using a modern browser (e.g., Google Chrome or Microsoft Edge) that doesn't already have the PWA installed.
2. Log in and open any dashboard (Owner, Manager, or Staff).
3. Observe the top navigation bar next to your profile.
   * *Expected Result*: An **Install App** button with a download icon appears.
4. Click the **Install App** button.
   * *Expected Result*: The browser's native app installation confirmation dialog displays.
5. Accept the installation.
   * *Expected Result*: The application installs, opens in its own standalone window, and the "Install App" button disappears.
6. Open the app in a browser where it is already installed.
   * *Expected Result*: The "Install App" button is hidden.

