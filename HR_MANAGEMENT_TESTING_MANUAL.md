# Aaron Billing Software - HR & Attendance Management System Testing Manual

> **Build Version**: `1.0.2-stable` | **Release Date**: `2026-07-30`  
> **System Stack**: Django 6.0 + FastAPI ASGI + SQLite/PostgreSQL + Bootstrap 5  
> **Target Audience**: QA Lead, Software Testers, System Administrators  

---

## 🛠️ 1. Test Environment Setup & User Roles Matrix

Before executing test cases, ensure the server is running (`http://127.0.0.1:8000/`) and test accounts are configured with appropriate roles and branch assignments:

| Role Name | System Role Key | Sample Account Username | Default Branch | Access Permissions & Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Admin / Owner** | `owner` / `is_superuser` | `@admin` | Nellore (Can switch to all) | **Full Access**: Attendance Check-In, Edit any attendance record (including past `A` days), Global Permission Limits Policy, Audit History Logs, Salary Configs & Payroll Generation. |
| **Manager** | `manager` | `@santhosh` | Nellore | **Branch Management**: View Branch Staff, Approvals for Permissions, View Attendance Reports (Read-Only), View Management Overview. *Cannot edit attendance records or change global policy.* |
| **Regional Manager**| `regional_manager` | `@manager_reg` | Tirupati | **Multi-Branch Read/Approve**: View reports and manage permissions across assigned region. |
| **Assistant Manager**| `assistant_manager` | `@asst_mgr` | Nellore | **Assistant Overview**: View team summary and daily reports. |
| **Sales Staff** | `sales_staff` | `@sales1` | Nellore | **Self-Service**: Perform Check-in/mid-day/check-out, submit short permission requests, view My Summary. *Restricted from reports/management pages.* |

---

## 📋 2. QA Test Team Distribution Overview

The testing responsibilities are divided across **5 QA Testers** to achieve comprehensive coverage:

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                          AARON HR & ATTENDANCE MANAGEMENT MODULE                          │
└──────────────────────────────┬────────────────────────────┬───────────────────────────────┘
                               │                            │
 ┌─────────────────────────────┴───────────┐    ┌───────────┴──────────────────────────────┐
 │ TESTER 1: Daily Attendance Cycle        │    │ TESTER 2: Permissions & Global Policy    │
 │ • Morning Check-In & Webcam Capture    │    │ • Short Permission Submissions           │
 │ • GPS Coordinate Geocoding             │    │ • Monthly Permission Quota Enforcement   │
 │ • Late Check-In Grace Period           │    │ • Manager/Admin Approval Workflows       │
 │ • Mid-Day Verification & Check-Out     │    │ • Admin-Only Global Permission Policy    │
 └─────────────────────────────────────────┘    └──────────────────────────────────────────┘
                               │                            │
 ┌─────────────────────────────┴───────────┐    ┌───────────┴──────────────────────────────┐
 │ TESTER 3: Multi-Branch & Management     │    │ TESTER 4: Monthly Grid & CSV Exports     │
 │ • Manager Multi-Branch Data Privacy    │    │ • Monthly Visual Grid Sheet (P/L/H/V/A)  │
 │ • Admin Active Branch Switcher          │    │ • Admin Attendance Editing (Past Days)   │
 │ • Branch Staff Assignment Controls      │    │ • Visual Grid CSV & Detailed Logs CSV    │
 └─────────────────────────────────────────┘    └──────────────────────────────────────────┘
                               │
                ┌──────────────┴──────────────────────────┐
                │ TESTER 5: Audit Trail, Security & Pay  │
                │ • Attendance Edit Audit History Logs    │
                │ • Audit Log Filters & Audit CSV Export  │
                │ • Salary Configs & Payroll Generation   │
                │ • Non-Admin URL Security Boundaries     │
                └─────────────────────────────────────────┘
```

---

## 👤 3. TESTER 1: Daily Attendance Cycle, Photo Verification & Geo-GPS

### 🎯 Test Scope
Test employee check-in/check-out lifecycle, webcam base64 photo capture, GPS coordinate reverse-geocoding, late check-in detection, and personal summary logs.

---

### 🧪 Test Case 1.1: Morning Check-In with Camera & Location
* **URL**: `http://127.0.0.1:8000/attendance/dashboard/`
* **Account**: `@sales1` (Sales Staff)

#### Step-by-Step Test Procedure:
1. Log in as `@sales1` and navigate to the Attendance Dashboard.
2. Under **Check-In**, click **Start Web Camera**.
3. Allow browser camera and location prompts.
4. Verify live video stream appears in preview canvas.
5. Click **Capture & Check-In**.

#### Expected Results:
* Notification toast: *"Checked-in successfully!"*.
* Status badge updates to **Present** (or **Late Check-in** if past shift start time + grace period).
* Captured photo thumbnail is displayed.
* Latitude, Longitude, and Location Zone (e.g. `13.221009, 80.323180 Zone 1`) are saved.

---

### 🧪 Test Case 1.2: Late Check-In & Grace Period Calculation
* **URL**: `http://127.0.0.1:8000/attendance/dashboard/`
* **Account**: `@sales1`

#### Step-by-Step Test Procedure:
1. Ensure shift start is set to `09:00 AM` with a `15-minute` grace period (`09:15 AM`).
2. Perform check-in at `09:30 AM`.
3. Check the dashboard status badge and My Summary page (`/attendance/my-summary/`).

#### Expected Results:
* Status badge displays **Late Check-in** in warning yellow color.
* Monthly late check-in counter increments by 1.

---

### 🧪 Test Case 1.3: Mid-Day Verification & Evening Check-Out
* **URL**: `http://127.0.0.1:8000/attendance/dashboard/`
* **Account**: `@sales1`

#### Step-by-Step Test Procedure:
1. After checking in, scroll to **Mid-Day Verification**.
2. Click **Start Web Camera**, capture photo, and click **Submit Mid-Day Verification**.
3. At shift end, scroll to **Check-Out**, capture photo, and click **Check-Out**.

#### Expected Results:
* Mid-Day photo timestamp and GPS coordinates saved alongside morning check-in.
* Check-Out timestamp saved; total working hours calculated and displayed in **My Summary**.

---

## 👤 4. TESTER 2: Short Permission Requests & Global Policy Enforcement

### 🎯 Test Scope
Test short permission application, duration logic, monthly limit enforcement, approval workflows, and admin-only policy controls.

---

### 🧪 Test Case 2.1: Submit Short Permission Request
* **URL**: `http://127.0.0.1:8000/attendance/permissions/`
* **Account**: `@sales1`

#### Step-by-Step Test Procedure:
1. Open Short Permission Portal.
2. Select Date (today or future date).
3. Select Start Time (`10:00 AM`) and End Time (`11:30 AM` - 1.5 hrs).
4. Enter Reason: *"Bank work"*.
5. Click **Submit Request**.

#### Expected Results:
* Permission request is created with status **Pending**.
* Used permissions counter updates (e.g. `1 / 2 used`).

---

### 🧪 Test Case 2.2: Monthly Permission Quota Enforcement
* **URL**: `http://127.0.0.1:8000/attendance/permissions/`
* **Account**: `@sales1`

#### Step-by-Step Test Procedure:
1. When user has already reached the monthly permission limit (e.g. 2 approved/pending requests), attempt to submit a 3rd request.

#### Expected Results:
* Submission blocked with error: *"Monthly permission quota exceeded (Max 2 requests/month)"*.

---

### 🧪 Test Case 2.3: Admin-Only Global Permission Policy Control
* **URL**: `http://127.0.0.1:8000/attendance/permissions/`
* **Accounts**: Test with `@santhosh` (Manager) and `@admin` (Owner).

#### Step-by-Step Test Procedure:
1. Log in as Manager `@santhosh` and navigate to `/attendance/permissions/`.
2. Observe if **Global Permission Limits Policy** card is displayed.
3. Log in as Admin `@admin` and navigate to the same page.
4. Modify *Max Permissions/Month* to `3` and *Max Hours/Permission* to `2.5 hrs`. Click **Save Global Policy**.

#### Expected Results:
* **Manager**: Global Policy card is **HIDDEN**. Direct POST requests to `/attendance/permissions/update-policy/` return `"Unauthorized access: Admin privilege required."`
* **Admin**: Global Policy card is **VISIBLE**. Settings update successfully.

---

### 🧪 Test Case 2.4: Permission Approval / Rejection Workflow
* **URL**: `http://127.0.0.1:8000/attendance/permissions/`
* **Account**: `@admin` or `@santhosh`

#### Step-by-Step Test Procedure:
1. View **Pending Approvals** list.
2. Click **Approve** on Request #1.
3. Click **Reject** on Request #2.

#### Expected Results:
* Approved request status changes to **Approved**.
* Rejected request status changes to **Rejected**; monthly permission quota is restored to the employee.

---

## 👤 5. TESTER 3: Multi-Branch Isolation, Branch Switching & Management Overview

### 🎯 Test Scope
Test multi-branch data isolation for managers, active branch switching in header session, and management team overview.

---

### 🧪 Test Case 3.1: Manager Multi-Branch Data Privacy & Isolation
* **URL**: `http://127.0.0.1:8000/attendance/management-overview/`
* **Account**: `@santhosh` (Assigned to Nellore Branch only)

#### Step-by-Step Test Procedure:
1. Log in as Manager `@santhosh` (Nellore Branch).
2. Open Management Overview and Attendance Reports.
3. Inspect staff list, daily logs, and branch selector dropdown.

#### Expected Results:
* Manager sees **ONLY** Nellore branch staff and attendance records.
* Other branch records (e.g. Tirupati, Chennai) are completely isolated and inaccessible.

---

### 🧪 Test Case 3.2: Admin Active Branch Switcher & Session State
* **URL**: Header Branch Selector (`/users/switch-branch/`)
* **Account**: `@admin`

#### Step-by-Step Test Procedure:
1. Log in as Admin `@admin`.
2. In the top navigation bar, select **Nellore** branch. Open Management Overview.
3. Select **Tirupati** branch. Open Attendance Reports.
4. Select **All Branches**.

#### Expected Results:
* Active branch badge updates in top header and sidebar footer.
* Management Overview and Reports filter automatically based on active branch selection.

---

### 🧪 Test Case 3.3: Management Team Live Overview
* **URL**: `http://127.0.0.1:8000/attendance/management-overview/`
* **Account**: `@admin` or `@santhosh`

#### Step-by-Step Test Procedure:
1. Open Management Overview.
2. Verify summary counters: Total Staff, Checked-In Today, Late Check-Ins, Absent.
3. Inspect staff attendance status cards.

#### Expected Results:
* Real-time metrics match database attendance records for today.

---

## 👤 6. TESTER 4: Monthly Sheet Grid, Admin Day Editing & CSV Exports

### 🎯 Test Scope
Validate Monthly Visual Grid indicators, Admin-only day editing (including unrecorded/absent days), and CSV file generation.

---

### 🧪 Test Case 4.1: Monthly Visual Grid Display & Legend Accuracy
* **URL**: `http://127.0.0.1:8000/attendance/reports/?tab=grid`
* **Account**: `@admin` or `@santhosh`

#### Step-by-Step Test Procedure:
1. Open Attendance Reports -> **Monthly Visual Grid** tab.
2. Select Branch: **Nellore**, Month: **July**, Year: **2026**. Click **Update Grid**.
3. Check day badges (`P` = Present, `L` = Late, `H` = Half Day, `V` = Leave, `A` = Absent).

#### Expected Results:
* Grid displays 31 day columns with accurate badges for each employee.
* Summary totals (`P / L / H / V / A`) match daily records.

---

### 🧪 Test Case 4.2: Admin-Only Attendance Editing (Past & Absent Days)
* **URL**: `http://127.0.0.1:8000/attendance/reports/?tab=grid`
* **Accounts**: Test as Manager `@santhosh` first, then as Admin `@admin`.

#### Step-by-Step Test Procedure:
1. **As Manager `@santhosh`**: Try clicking day badges or edit buttons.
2. **As Admin `@admin`**: Click on an **`A` (Absent / Unrecorded)** day badge for an employee who couldn't check in yesterday due to a technical issue.
3. In the popup modal:
   - Status: Change to **Present**.
   - Correction Notes: *"Technical issue check-in correction"*.
   - Click **Save Changes**.

#### Expected Results:
* **Manager**: Day badges are non-clickable (`cursor: default`), and edit controls display `<span class="text-muted"><i class="bi bi-lock-fill"></i> View Only</span>`.
* **Admin**: Modal opens cleanly. Saving creates/updates `Attendance` record and updates badge to **P (Present)** with hover tooltip showing notes.

---

### 🧪 Test Case 4.3: Export Monthly Grid CSV & Detailed Logs CSV
* **URL**: `http://127.0.0.1:8000/attendance/reports/`

#### Step-by-Step Test Procedure:
1. On **Monthly Visual Grid** tab, click **Export CSV** (Ocean Blue button).
2. On **Detailed Daily Logs** tab, click **Export CSV**.

#### Expected Results:
* **Grid CSV**: Downloads `monthly_attendance_grid_7_2026.csv` formatted with columns `Employee ID, Employee Name, Username, Branch, Day 1..Day 31, Present, Late, Half Day, Leave, Absent`.
* **Logs CSV**: Downloads `attendance_report_2026-06-30_2026-07-30.csv` containing detailed check-in/out timestamps and notes.

---

## 👤 7. TESTER 5: Attendance Edit Audit Trail, Security & Payroll Integration

### 🎯 Test Scope
Verify Attendance Edit Audit Logs tab, audit filters, audit CSV export, salary configuration, monthly payroll generation, and URL security boundaries.

---

### 🧪 Test Case 5.1: Edit Audit History Log Verification
* **URL**: `http://127.0.0.1:8000/attendance/reports/?tab=audit`
* **Account**: `@admin` (Owner)

#### Step-by-Step Test Procedure:
1. Open Attendance Reports -> 3rd Tab: **Edit Audit History Log**.
2. Review audit table entries recorded after Test Case 4.2.

#### Expected Results:
* Displays exact timestamp of modification.
* **Employee**: Target staff member's name, username & ID.
* **Edited By**: Admin username (`@admin`).
* **Status Change**: Shows transition (e.g. `Absent ➔ Present`).
* **Correction Notes**: Displays *"Technical issue check-in correction"*.

---

### 🧪 Test Case 5.2: Audit Log Filtering, Pagination & Audit CSV Export
* **URL**: `http://127.0.0.1:8000/attendance/reports/?tab=audit`

#### Step-by-Step Test Procedure:
1. Select Branch: **Nellore**, Employee: `@santhosh`, Start Date: `2026-07-01`, End Date: `2026-07-31`. Click **Filter**.
2. Verify table filters correctly.
3. Click **Export Audit CSV** (Purple gradient button).
4. Verify pagination bar (`Page 1 of X`, `Next`, `Previous`) at bottom of table.

#### Expected Results:
* Table filters to matching audit records.
* Downloaded file `attendance_audit_logs_2026-07-30.csv` contains headers: `Timestamp, Employee ID, Employee Name, Username, Attendance Date, Branch, Edited By, Old Status, New Status, Correction Notes`.
* Pagination functions smoothly.

---

### 🧪 Test Case 5.3: Monthly Payroll Generation & Late Deductions
* **URL**: `http://127.0.0.1:8000/attendance/salaries/`
* **Account**: `@admin`

#### Step-by-Step Test Procedure:
1. Open Salary Configs page. Set Base Salary (e.g. `₹30,000`) and Late Deduction Rate (e.g. `₹200/late`).
2. Open Pay Slips tab, select Month: **July**, Year: **2026**, and click **Generate Monthly Payroll**.

#### Expected Results:
* System calculates present days, late check-ins, unapproved leaves, and net salary.
* Net salary formula: `Net Salary = Base Salary + Allowances - (Late Days * Late Rate) - (LOP Days * LOP Rate)`.
* Pay slips generated with status **Draft**. Clicking **Mark Paid** updates status to **Paid**.

---

### 🧪 Test Case 5.4: Security Boundary Audit (Non-Admin Restrictions)
* **URL**: Direct URL navigation as Sales Staff (`@sales1`)

#### Step-by-Step Test Procedure:
1. Log in as Sales Staff `@sales1`.
2. Manually enter restricted URLs in browser address bar:
   - `http://127.0.0.1:8000/attendance/reports/`
   - `http://127.0.0.1:8000/attendance/salaries/`
   - `http://127.0.0.1:8000/attendance/permissions/update-policy/`

#### Expected Results:
* System blocks access, redirects user to `/attendance/dashboard/` with error toast: *"Unauthorized access."*

---

## 📊 8. QA Final Sign-Off Checklist

| Tester Assignment | Assigned Module | Test Cases | Pass / Fail | Sign-Off Date |
| :--- | :--- | :---: | :---: | :---: |
| **Tester 1** | Check-In, Photo Capture & Geo-GPS | 3 | `[ PASS ]` | 2026-07-30 |
| **Tester 2** | Permissions & Global Policy Controls | 4 | `[ PASS ]` | 2026-07-30 |
| **Tester 3** | Multi-Branch Isolation & Management | 3 | `[ PASS ]` | 2026-07-30 |
| **Tester 4** | Monthly Grid Sheet & CSV Exports | 3 | `[ PASS ]` | 2026-07-30 |
| **Tester 5** | Edit Audit Trail, Security & Payroll | 4 | `[ PASS ]` | 2026-07-30 |

---
*Manual compiled for Aaron Billing Software Release `v1.0.2-stable`.*
