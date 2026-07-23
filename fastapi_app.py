from fastapi import FastAPI, APIRouter, Query, HTTPException, Request, Depends
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

# ----------------- ATTENDANCE ENDPOINTS -----------------

from pydantic import BaseModel
import base64
from django.core.files.base import ContentFile
import base64
from io import BytesIO
from PIL import Image
import logging

logger = logging.getLogger(__name__)

class AttendanceActionRequest(BaseModel):
    photo: str  # base64 encoded photo
    lat: float
    lng: float

def get_file_from_base64(base64_str, filename):
    if not base64_str:
        return None
    try:
        if ';base64,' in base64_str:
            format_str, imgstr = base64_str.split(';base64,')
            img_data = base64.b64decode(imgstr)
            
            # Load with Pillow to resize and compress
            img = Image.open(BytesIO(img_data))
            
            # Convert to RGB mode if RGBA/PNG
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize if dimensions exceed 640px
            max_size = 640
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Compress and save to buffer as JPEG
            output = BytesIO()
            img.save(output, format='JPEG', quality=60, optimize=True)
            output.seek(0)
            
            return ContentFile(output.read(), name=f"{filename}.jpg")
    except Exception as e:
        logger.error(f"Error parsing/compressing base64 image: {e}")
    return None

def get_current_user(request: Request):
    session_key = request.cookies.get("sessionid")
    if not session_key:
        raise HTTPException(
            status_code=401,
            detail="Session cookie 'sessionid' is missing. Please log in."
        )
    
    from django.contrib.sessions.models import Session
    from django.contrib.auth import get_user_model
    
    try:
        session = Session.objects.get(session_key=session_key)
        uid = session.get_decoded().get("_auth_user_id")
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="Invalid session: User ID not found in session."
            )
        User = get_user_model()
        user = User.objects.get(pk=uid)
        return user
    except Session.DoesNotExist:
        raise HTTPException(
            status_code=401,
            detail="Session does not exist or has expired."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Authentication error: {str(e)}"
        )
@router.post("/attendance/check-in")
def api_check_in(payload: AttendanceActionRequest, current_user = Depends(get_current_user), request: Request = None):
    try:
        from django.utils import timezone
        from attendance.models import Attendance, LeaveRequest
        
        today = timezone.localdate()
        
        # Check if already checked in
        existing = Attendance.objects.filter(user=current_user, date=today).first()
        if existing and existing.check_in:
            raise HTTPException(status_code=400, detail="Already checked in for today.")
            
        photo_file = get_file_from_base64(payload.photo, f"{current_user.username}_checkin_{today}")
        if not photo_file:
            raise HTTPException(status_code=400, detail="Photo capture is required and must be valid base64.")
            
        branch = current_user.active_branch
        if not branch:
            branch = current_user.branches.first()
            if not branch:
                raise HTTPException(status_code=400, detail="No branch assigned to user.")
                
        now = timezone.localtime(timezone.now())
        status_str = 'present'
        if now.hour > 10 or (now.hour == 10 and now.minute > 15):
            status_str = 'late'
            
        on_leave = LeaveRequest.objects.filter(
            user=current_user,
            start_date__lte=today,
            end_date__gte=today,
            status='approved'
        ).exists()
        if on_leave:
            status_str = 'on_leave'
            
        if existing:
            existing.check_in = timezone.now()
            existing.check_in_photo = photo_file
            existing.check_in_lat = Decimal(str(payload.lat))
            existing.check_in_lng = Decimal(str(payload.lng))
            existing.status = status_str
            existing.save()
            att = existing
        else:
            att = Attendance.objects.create(
                user=current_user,
                branch=branch,
                date=today,
                check_in=timezone.now(),
                check_in_photo=photo_file,
                check_in_lat=Decimal(str(payload.lat)),
                check_in_lng=Decimal(str(payload.lng)),
                status=status_str
            )
            
        return {
            "success": True,
            "message": "Checked in successfully!",
            "status": att.status,
            "time": timezone.localtime(att.check_in).strftime('%I:%M %p')
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check-in failed: {str(e)}")

@router.post("/attendance/mid-day")
def api_mid_day(payload: AttendanceActionRequest, current_user = Depends(get_current_user)):
    try:
        from django.utils import timezone
        from attendance.models import Attendance
        
        today = timezone.localdate()
        
        attendance = Attendance.objects.filter(user=current_user, date=today).first()
        if not attendance:
            raise HTTPException(status_code=400, detail="Please check-in first before mid-day verification.")
            
        if attendance.mid_day_time:
            raise HTTPException(status_code=400, detail="Mid-day verification already completed.")
            
        photo_file = get_file_from_base64(payload.photo, f"{current_user.username}_midday_{today}")
        if not photo_file:
            raise HTTPException(status_code=400, detail="Photo capture is required and must be valid base64.")
            
        attendance.mid_day_time = timezone.now()
        attendance.mid_day_photo = photo_file
        attendance.mid_day_lat = Decimal(str(payload.lat))
        attendance.mid_day_lng = Decimal(str(payload.lng))
        attendance.save()
        
        return {
            "success": True,
            "message": "Mid-day verification completed successfully!",
            "time": timezone.localtime(attendance.mid_day_time).strftime('%I:%M %p')
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mid-day verification failed: {str(e)}")

@router.post("/attendance/check-out")
def api_check_out(payload: AttendanceActionRequest, current_user = Depends(get_current_user)):
    try:
        from django.utils import timezone
        from attendance.models import Attendance
        
        today = timezone.localdate()
        
        attendance = Attendance.objects.filter(user=current_user, date=today).first()
        if not attendance:
            raise HTTPException(status_code=400, detail="Please check-in first before checking out.")
            
        if attendance.check_out:
            raise HTTPException(status_code=400, detail="Already checked out for today.")
            
        photo_file = get_file_from_base64(payload.photo, f"{current_user.username}_checkout_{today}")
        if not photo_file:
            raise HTTPException(status_code=400, detail="Photo capture is required and must be valid base64.")
            
        attendance.check_out = timezone.now()
        attendance.check_out_photo = photo_file
        attendance.check_out_lat = Decimal(str(payload.lat))
        attendance.check_out_lng = Decimal(str(payload.lng))
        attendance.save()
        
        return {
            "success": True,
            "message": "Checked out successfully!",
            "time": timezone.localtime(attendance.check_out).strftime('%I:%M %p')
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Check-out failed: {str(e)}")

@router.get("/attendance/today-status")
def api_today_status(current_user = Depends(get_current_user)):
    try:
        from django.utils import timezone
        from attendance.models import Attendance
        
        today = timezone.localdate()
        att = Attendance.objects.filter(user=current_user, date=today).first()
        
        if not att:
            return {
                "date": today.isoformat(),
                "checked_in": False,
                "mid_day_completed": False,
                "checked_out": False,
                "status": "absent"
            }
            
        return {
            "date": today.isoformat(),
            "checked_in": att.check_in is not None,
            "check_in_time": timezone.localtime(att.check_in).strftime('%I:%M %p') if att.check_in else None,
            "mid_day_completed": att.mid_day_time is not None,
            "mid_day_time": timezone.localtime(att.mid_day_time).strftime('%I:%M %p') if att.mid_day_time else None,
            "checked_out": att.check_out is not None,
            "check_out_time": timezone.localtime(att.check_out).strftime('%I:%M %p') if att.check_out else None,
            "status": att.status
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch today's status: {str(e)}")

@router.get("/attendance/history")
def api_attendance_history(limit: int = 10, current_user = Depends(get_current_user)):
    try:
        from attendance.models import Attendance
        
        records = Attendance.objects.filter(user=current_user).order_by('-date')[:limit]
        
        result = []
        for att in records:
            result.append({
                "date": att.date.isoformat(),
                "check_in": att.check_in.isoformat() if att.check_in else None,
                "mid_day_time": att.mid_day_time.isoformat() if att.mid_day_time else None,
                "check_out": att.check_out.isoformat() if att.check_out else None,
                "status": att.status,
                "notes": att.notes
            })
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch attendance history: {str(e)}")

app.include_router(router)
