from fastapi import FastAPI, APIRouter, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, date

app = FastAPI(title="Aaron Billing High-Performance API", version="1.0")

# Adjust origins as needed – allow the Render domain and any local dev URLs
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aaron-billing-software1-nn2t.onrender.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()

# Helper to import Django models dynamically or after Django setup is guaranteed
# (We already do django.setup() in config/asgi.py, so we can import directly)
from core.models import Branch, Product, ProductRegistry
from billing.models import Bill, BillItem

@router.get("/ping")
def ping():
    return {"msg": "pong", "time": datetime.now().isoformat()}

@router.get("/branches")
def get_branches():
    """Get all branches in the system"""
    branches = Branch.objects.all().order_by('name')
    return [
        {
            "id": b.id,
            "name": b.name,
            "location": b.location,
            "contact_number": b.contact_number,
            "invoice_prefix": b.invoice_prefix,
            "code": b.code
        }
        for b in branches
    ]

@router.get("/products")
def get_products(branch_id: int, query: Optional[str] = None):
    """Get products under a specific branch with stock levels"""
    registry_qs = ProductRegistry.objects.filter(branch_id=branch_id).select_related('product')
    if query:
        registry_qs = registry_qs.filter(product__name__icontains=query) | registry_qs.filter(product__barcode__icontains=query)
    
    # Limit to 100 for high performance
    registries = registry_qs[:100]
    
    return [
        {
            "product_id": r.product.id,
            "name": r.product.name,
            "barcode": r.product.barcode,
            "price": float(r.product.price),
            "size": r.product.size,
            "stock_quantity": r.stock_quantity,
            "damaged_qty": r.damaged_qty,
            "low_stock_threshold": r.low_stock_threshold
        }
        for r in registries
    ]

@router.get("/bills")
def get_bills(branch_id: int, limit: int = 20):
    """Retrieve last N bills for a branch"""
    bills = Bill.objects.filter(branch_id=branch_id).order_by('-created_at')[:limit]
    return [
        {
            "id": b.id,
            "invoice_number": b.invoice_number,
            "customer_name": b.customer_name,
            "customer_phone": b.customer_phone,
            "total_amount": float(b.total_amount),
            "retail_price": float(b.retail_price),
            "payment_method": b.payment_method,
            "created_at": b.created_at.isoformat(),
            "has_returns": b.has_returns
        }
        for b in bills
    ]

@router.get("/stats")
def get_stats(branch_id: int):
    """Get fast dashboard statistics for today's sales in a branch"""
    today = date.today()
    bills_today = Bill.objects.filter(branch_id=branch_id, created_at__date=today)
    
    total_sales = Decimal('0')
    cash_total = Decimal('0')
    online_total = Decimal('0')
    bill_count = bills_today.count()
    
    for b in bills_today:
        total_sales += b.total_amount
        cash_total += b.cash_amount
        online_total += b.online_amount
        
    return {
        "branch_id": branch_id,
        "date": today.isoformat(),
        "total_sales": float(total_sales),
        "cash_sales": float(cash_total),
        "online_sales": float(online_total),
        "bill_count": bill_count
    }

app.include_router(router)
