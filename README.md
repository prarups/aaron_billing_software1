# Aaron Billing Software ⚡

A high-performance, vibrant, and multi-branch POS & Inventory Management System built with Django.

## ✨ "Vibrant Premium" Experience
Aaron Billing is designed with a **Vibrant Premium** aesthetic—combining productivity with a stunning, modern UI.
- **Glassmorphism & Gradients**: A sleek, translucent design that feels light and professional.
- **Micro-Animations**: Smooth transitions and interactive feedback for a premium user experience.
- **Mobile-First POS**: A lightning-fast, responsive billing interface optimized for both tablets and smartphones.

## 🚀 Key Features
- **Multi-Branch Management**: Seamlessly switch between branches. Data is dynamically filtered based on your active session.
- **Intelligent Inventory**: Global product registry with branch-specific stock levels and low-stock alerts.
- **Advanced POS**: 
  - Real-time cart management.
  - Built-in Barcode Scanner (Webcam-based).
  - Instant AJAX-based product lookup.
- **Digital Receipts**: 
  - Unique sharing IDs for every bill.
  - **WhatsApp Integration**: Send professional receipt links directly to customers.
  - Public-facing receipt view for customer convenience.
- **Comprehensive Reporting**: 
  - Daily staff activity dashboards.
  - Multi-branch sales reports with CSV export.
  - Dynamic date and branch filtering.

## 🛠️ Technology Stack
- **Backend**: Django 6.0 (Python)
- **Database**: PostgreSQL (Production) / SQLite (Local)
- **Frontend**: Bootstrap 5, Vanilla JS, Google Fonts (Inter)
- **Deployment**: Railway (optimised for `gunicorn` & `whitenoise`)

## 💻 Local Setup
1. **Clone & Install**:
   ```bash
   git clone <repo-url>
   cd aaron_billing_software
   pip install -r requirements.txt
   ```
2. **Environment**:
   Copy `.env.example` to `.env` (if applicable) or set:
   - `DEBUG=True`
   - `SECRET_KEY=your-key`
3. **Database**:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```
4. **Run Server**:
   ```bash
   python manage.py runserver
   ```

## 🌐 Production Deployment (Railway)
This project is configured for one-click deployment on Railway using `Procfile` and `railway.json`.
- Ensure `DATABASE_URL` and `SECRET_KEY` are set in Railway variables.
- `DEBUG` should be `False` for production security.

---
*For a deep dive into the technical architecture, see [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).*
