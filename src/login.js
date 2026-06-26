/* login.js – handles the unified sign‑in flow */

// Adjust this URL if your auth endpoint lives elsewhere
const AUTH_URL = '/api/auth/login'; // expects JSON { email, password } and returns { token }

// Utility to set a HttpOnly cookie via server Set-Cookie header.
// For demo purposes we store the token in localStorage (dev only).
function storeToken(token) {
  // In production you should have the server set an HttpOnly SameSite cookie.
  // Here we fallback to localStorage so the UI can read it.
  try {
    localStorage.setItem('authToken', token);
  } catch (e) {
    console.error('Token storage failed', e);
  }
}

function getRedirectTarget() {
  // After successful login we send the user to the module picker.
  // You could also add logic to remember the page the user originally tried to open.
  return 'module_picker.html';
}

async function handleLogin(event) {
  event.preventDefault();
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;

  const payload = { email, password };
  try {
    const resp = await fetch(AUTH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error('Invalid credentials');
    const data = await resp.json();
    const token = data.token;
    if (!token) throw new Error('No token returned');
    storeToken(token);
    // Redirect to picker (full page load to reset state)
    window.location.href = getRedirectTarget();
  } catch (err) {
    console.error('Login error', err);
    const errDiv = document.getElementById('errorMsg');
    errDiv.textContent = err.message || 'Login failed';
    errDiv.style.display = 'block';
  }
}

// Attach listener once DOM is ready
window.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  form.addEventListener('submit', handleLogin);
});
