# Aaron Billing Software - 5-Tester Manual Testing Plan

This document outlines the testing responsibilities and step-by-step verification guidelines for a team of 5 manual testers.

---

## 👥 Tester Assignment Overview

| Tester | Focus Area | Key Features Tested |
| :--- | :--- | :--- |
| **Tester 1** | **Authentication, Access Control & PWA** | Login (Username/Emp ID), Role Restrictions, Staff Deactivation, PWA Installation |
| **Tester 2** | **Branches & Dashboard Navigation** | Branch CRUD, Branch Search (Code/Name), Tab Navigation, Overview Reporting |
| **Tester 3** | **Product Master & Bulk CSV Operations** | Product View/Edit, Inline Price/Stock Edits, Bulk CSV Upload & Stock Accumulation |
| **Tester 4** | **Reconciliation & Stock Ledgers** | Multi-Branch Stock Report, Damage Logging, Adjustment Permissions |
| **Tester 5** | **POS Billing & Returns Management** | Cart Checkout, Split Payments, Invoice Printing, Sales Filters, Returns Processing |

---

## 📋 Tester 1: Authentication, Access Control & PWA
### Goal: Verify secure entry, user permission enforcement, and Progressive Web App features.

#### 1. Login Functionality
* **Step 1.1**: Go to the login page. Attempt login using a standard **username** (e.g. `admin`) and **password** (`Praveen@123`). Verify successful redirect to the dashboard.
* **Step 1.2**: Log out. Attempt login using the **Employee ID** (e.g., `AR0001` or another staff member's ID) and their password. Verify successful authentication.
* **Step 1.3**: Ask **Tester 2** (Admin) to temporarily deactivate a test staff account. Attempt to log in with that deactivated account.
  * *Expected Result*: Warning message appears: `"Your account is inactive. Please contact admin team."`

#### 2. Staff Management Actions (View Only)
* **Step 2.1**: Go to the **Staff** tab. Attempt to toggle your own account status.
  * *Expected Result*: The toggle switch is disabled; tooltip shows `"You cannot deactivate your own account"`.
* **Step 2.2**: Log in as a Manager. Try to access the Owner Dashboard.
  * *Expected Result*: Redirection back to the dashboard with an access warning.

#### 3. PWA App Installation
* **Step 3.1**: Open the app in Chrome/Edge on a desktop or phone.
* **Step 3.2**: Check the navbar for the **"Install App"** download icon. Click it and confirm the prompt.
  * *Expected Result*: App installs, launches in its own standalone window, and the button disappears.

---

## 📋 Tester 2: Branches & Dashboard Navigation
### Goal: Verify branch creation, data filtering, and dashboard search.

#### 1. Branch CRUD
* **Step 1.1**: Open the **Branches** tab. Click **"Create Branch"**. Fill in details (Name: `West Branch`, Location: `Avenue Road`, Prefix: `WB`). Save.
  * *Expected Result*: Branch is added, and its code is auto-assigned starting at `10001`.
* **Step 1.2**: Click the edit pencil icon next to the branch. Modify its Location and save. Confirm the values update immediately.
* **Step 1.3**: Click the delete trash icon next to a test branch. Confirm the deletion.

#### 2. Branch Search & Page Navigation
* **Step 2.1**: In the **Branches** tab search input, search by name (e.g., `West`).
  * *Expected Result*: The table instantly filters to show only matching branches.
* **Step 2.2**: Search by code (e.g., `10001`).
  * *Expected Result*: The table instantly filters to show only the matching branch code.
* **Step 2.3**: Verify the bottom of the table shows the count: `"Showing X to Y of Z branches"`. Test page navigation buttons if more than 10 branches exist.

#### 3. Overview Reports
* **Step 3.1**: In the **Home** tab, verify overall stats show count cards (Sales, Branches, Products).
* **Step 3.2**: Click **"Export CSV"** and open the downloaded file. Confirm it lists today's sales transactions.

---

## 📋 Tester 3: Product Master & Bulk CSV Operations
### Goal: Verify product registry, inline edits, CSV bulk imports, and permissions.

#### 1. Product Master Permissions
* **Step 1.1**: Log in as a Manager **WITHOUT** product rights. Access `/core/products/`.
  * *Expected Result*: Add/Bulk buttons are hidden, and table items (prices/stock) are read-only.
* **Step 1.2**: Log in as an Admin or Manager **WITH** product rights. Access `/core/products/`.
  * *Expected Result*: Add/Bulk buttons appear, and clicking prices/stock opens inline edit fields.

#### 2. Inline Price / Stock Editing
* **Step 2.1**: Click a product's price cell. Input a new price and press enter.
  * *Expected Result*: The cell updates and saves dynamically without a page reload.
* **Step 2.2**: Repeat the same for a stock cell and verify.

#### 3. Bulk CSV Upload & Stock Accumulation
* **Step 3.1**: Click **"Bulk Insert"** -> **"Download Template"**.
* **Step 3.2**: Add a row: Name: `Test Item`, Barcode: `TESTBAR99`, Price: `100`, Initial Stock: `10`, Branch Code: `10001`. Upload it. Verify the item appears in the product master.
* **Step 3.3**: Prepare a second CSV file. Add the exact same barcode `TESTBAR99` but set stock to `5`. Upload it.
  * *Expected Result*: The product's total stock in the table updates to `15` (accumulated: `10 + 5`) instead of being overwritten.

---

## 📋 Tester 4: Reconciliation & Stock Ledgers
### Goal: Verify stock levels, damage logging, and adjustment auditing.

#### 1. Multi-Branch Stock Report
* **Step 1.1**: Access the **Multi-Branch Stock Report**. Expand a product row.
  * *Expected Result*: Aggregated inventory columns (Opening, Incoming, Outgoing, Damaged, Closing) are displayed for each branch.

#### 2. Stock Adjustment (Damage / Correction Logging)
* **Step 2.1**: Log in as an authorized user. Expand a product row in the report. Click the **wrench/Correction icon**.
* **Step 2.2**: Log a correction: enter `-3` units, select reason **"Damage"**, and save.
  * *Expected Result*: Closing stock is reduced by 3.
* **Step 2.3**: Expand the row again. Confirm that the **"Dmg"** count has increased by `3` and a transaction log is recorded.

#### 3. Authorization Check
* **Step 3.1**: Log in as a Manager **WITHOUT** rights.
  * *Expected Result*: The correction wrench icon is completely hidden. Manually trying to access `/core/products/adjust-stock/<id>/` redirects you to the product list with a permission error.

---

## 📋 Tester 5: POS Terminal, Split Billing & Sales Reports
### Goal: Verify POS sales checkout, receipt generation, and returns processing.

#### 1. POS Checkout & Split Payments
* **Step 1.1**: Open the **POS page**. Search a product by name/barcode. Add it to the cart.
* **Step 1.2**: Apply a `10%` discount in the cart panel. Verify the total amount updates.
* **Step 1.3**: Select payment method **"Split"**. Enter `100` cash, and place the rest online. Submit.
  * *Expected Result*: Sale completes, and the invoice print layout preview window pops up automatically.

#### 2. Sales Report Filters
* **Step 2.1**: Open the **Sales Report**. Verify filters (date picker, payment methods: Cash, Online, Split) successfully isolate matching bills.

#### 3. Returns Processing
* **Step 3.1**: On the Sales Report page, locate the transaction you checked out in **Step 1.3**.
* **Step 3.2**: Click **"Return Request"** next to a line item, enter quantity, select a reason, and process.
  * *Expected Result*: Transaction status updates, and stock is returned to the inventory ledger (verifiable by **Tester 4** in the Stock Report).
