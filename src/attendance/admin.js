/* admin.js – client side logic for the Attendance Admin Dashboard */

// Base API prefix (adjust if your dev server runs on a different port)
const API_BASE = '/api/attendance/admin';

// Elements
const totalEmployeesEl = document.getElementById('totalEmployees');
const todayPunchInsEl = document.getElementById('todayPunchIns');
const pendingLeavesEl = document.getElementById('pendingLeaves');

const attendanceTableBody = document.querySelector('#attendanceTable tbody');
const leavesTableBody = document.querySelector('#leavesTable tbody');
const payrollTableBody = document.querySelector('#payrollTable tbody');

const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modalTitle');
const modalForm = document.getElementById('modalForm');

let currentEntity = null; // 'attendance' | 'leaves' | 'payroll'
let editRecordId = null; // set when editing

/*** Utility ***/
function formatDate(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleDateString();
}
function formatTime(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
}
/*** Data loading ***/
async function loadOverview() {
  try {
    const res = await fetch(`${API_BASE}/overview`);
    const data = await res.json();
    totalEmployeesEl.textContent = data.totalEmployees;
    todayPunchInsEl.textContent = data.todayPunchIns;
    pendingLeavesEl.textContent = data.pendingLeaves;
  } catch (e) {
    console.error('Overview load error', e);
  }
}

async function loadAttendance() {
  attendanceTableBody.innerHTML = '';
  const res = await fetch(`${API_BASE}/records?type=attendance`);
  const rows = await res.json();
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.employeeName}</td>
      <td>${formatDate(r.date)}</td>
      <td>${formatTime(r.punchIn)}</td>
      <td>${r.punchOut ? formatTime(r.punchOut) : '--'}</td>
      <td>${r.location || '--'}</td>
      <td>${r.photoUrl ? `<img src="${r.photoUrl}" style="height:30px;"/>` : '--'}</td>
      <td>
        <button class="add-btn" onclick="openModal('attendance', ${r.id})">Edit</button>
        <button class="add-btn" style="background:#ef4444" onclick="deleteRecord('attendance', ${r.id})">Del</button>
      </td>
    `;
    attendanceTableBody.appendChild(tr);
  });
}

async function loadLeaves() {
  leavesTableBody.innerHTML = '';
  const res = await fetch(`${API_BASE}/records?type=leaves`);
  const rows = await res.json();
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.employeeName}</td>
      <td>${r.leaveType}</td>
      <td>${formatDate(r.fromDate)}</td>
      <td>${formatDate(r.toDate)}</td>
      <td>${r.status}</td>
      <td>
        <button class="add-btn" onclick="openModal('leaves', ${r.id})">Edit</button>
        <button class="add-btn" style="background:#ef4444" onclick="deleteRecord('leaves', ${r.id})">Del</button>
      </td>
    `;
    leavesTableBody.appendChild(tr);
  });
}

async function loadPayroll() {
  payrollTableBody.innerHTML = '';
  const res = await fetch(`${API_BASE}/records?type=payroll`);
  const rows = await res.json();
  rows.forEach(r => {
    const net = (Number(r.base) + Number(r.bonus) - Number(r.deductions)).toFixed(2);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.employeeName}</td>
      <td>${r.base}</td>
      <td>${r.bonus}</td>
      <td>${r.deductions}</td>
      <td>${net}</td>
      <td>
        <button class="add-btn" onclick="openModal('payroll', ${r.id})">Edit</button>
        <button class="add-btn" style="background:#ef4444" onclick="deleteRecord('payroll', ${r.id})">Del</button>
      </td>
    `;
    payrollTableBody.appendChild(tr);
  });
}

/*** Modal handling ***/
function openModal(entity, id = null) {
  currentEntity = entity;
  editRecordId = id;
  modalTitle.textContent = id ? `Edit ${entity}` : `Add New ${entity}`;
  modalForm.innerHTML = '';
  // Build form fields based on entity type
  if (entity === 'attendance') {
    modalForm.innerHTML = `
      <label>Employee ID <input type="text" name="employeeId" required /></label>
      <label>Date <input type="date" name="date" required /></label>
      <label>Punch In <input type="time" name="punchIn" required /></label>
      <label>Punch Out <input type="time" name="punchOut" /></label>
      <label>Location <input type="text" name="location" /></label>
      <label>Photo URL <input type="url" name="photoUrl" /></label>
      <button type="submit">Save</button>
    `;
    if (id) loadEntityData(entity, id);
  } else if (entity === 'leaves') {
    modalForm.innerHTML = `
      <label>Employee ID <input type="text" name="employeeId" required /></label>
      <label>Leave Type <select name="leaveType" required><option value="Annual">Annual</option><option value="Sick">Sick</option><option value="Unpaid">Unpaid</option></select></label>
      <label>From <input type="date" name="fromDate" required /></label>
      <label>To <input type="date" name="toDate" required /></label>
      <label>Status <select name="status" required><option value="Pending">Pending</option><option value="Approved">Approved</option><option value="Rejected">Rejected</option></select></label>
      <button type="submit">Save</button>
    `;
    if (id) loadEntityData(entity, id);
  } else if (entity === 'payroll') {
    modalForm.innerHTML = `
      <label>Employee ID <input type="text" name="employeeId" required /></label>
      <label>Base Salary <input type="number" step="0.01" name="base" required /></label>
      <label>Bonus <input type="number" step="0.01" name="bonus" /></label>
      <label>Deductions <input type="number" step="0.01" name="deductions" /></label>
      <button type="submit">Save</button>
    `;
    if (id) loadEntityData(entity, id);
  }
  modal.style.display = 'flex';
}

function closeModal() {
  modal.style.display = 'none';
  currentEntity = null;
  editRecordId = null;
}

async function loadEntityData(entity, id) {
  try {
    const res = await fetch(`${API_BASE}/records/${entity}/${id}`);
    const data = await res.json();
    // Populate form fields
    Object.entries(data).forEach(([key, value]) => {
      const input = modalForm.querySelector(`[name="${key}"]`);
      if (input) input.value = value;
    });
  } catch (e) {
    console.error('Failed to load entity data', e);
  }
}

/*** Form submit ***/
async function handleSubmit(e) {
  e.preventDefault();
  const formData = new FormData(modalForm);
  const payload = {};
  formData.forEach((v, k) => payload[k] = v);

  const method = editRecordId ? 'PUT' : 'POST';
  const url = editRecordId ? `${API_BASE}/records/${currentEntity}/${editRecordId}` : `${API_BASE}/records/${currentEntity}`;

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Server error');
    // Refresh tables
    if (currentEntity === 'attendance') await loadAttendance();
    else if (currentEntity === 'leaves') await loadLeaves();
    else if (currentEntity === 'payroll') await loadPayroll();
    closeModal();
  } catch (err) {
    alert('Failed to save record');
    console.error(err);
  }
}

/*** Delete ***/
async function deleteRecord(entity, id) {
  if (!confirm('Are you sure you want to delete this record?')) return;
  try {
    const res = await fetch(`${API_BASE}/records/${entity}/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Delete failed');
    if (entity === 'attendance') await loadAttendance();
    else if (entity === 'leaves') await loadLeaves();
    else if (entity === 'payroll') await loadPayroll();
  } catch (e) {
    alert('Delete failed');
    console.error(e);
  }
}

/*** Init ***/
window.addEventListener('DOMContentLoaded', async () => {
  await loadOverview();
  await loadAttendance();
  await loadLeaves();
  await loadPayroll();
  // logout button (example stub)
  const logoutBtn = document.getElementById('logoutBtn');
  logoutBtn.addEventListener('click', () => {
    // Clear auth token and redirect – replace with real logic.
    localStorage.removeItem('authToken');
    window.location.href = '/login.html';
  });
});

// Expose for HTML inline handlers
window.openModal = openModal;
window.closeModal = closeModal;
window.handleSubmit = handleSubmit;
window.deleteRecord = deleteRecord;
