import base64
import json
import csv
from io import BytesIO
from PIL import Image
import logging

logger = logging.getLogger(__name__)
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.core.files.base import ContentFile
from django.db.models import Count, Q, Sum
from django.conf import settings
from users.models import User
from core.models import Branch
from .models import Attendance, LeaveRequest, PermissionRequest, SalaryConfig, MonthlyPayroll, GlobalPermissionPolicy, AttendanceAuditLog
import datetime
import calendar
from decimal import Decimal
from django.db import transaction

def get_file_from_base64(base64_str, filename):
    if not base64_str:
        return None
    try:
        if ';base64,' in base64_str:
            format, imgstr = base64_str.split(';base64,')
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

def is_owner(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_owner()

def is_manager_or_owner(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_owner() or user.role == 'regional_manager':
        return True
    return user.is_manager()

def auto_update_past_attendance_statuses():
    try:
        today = timezone.localdate()
        past_records = Attendance.objects.filter(date__lt=today, status='checked_in')
        for att in past_records:
            att.recalculate_status()
            att.save()
    except Exception as e:
        logger.error(f"Error auto updating past attendance statuses: {e}")

@login_required
def attendance_dashboard(request):
    auto_update_past_attendance_statuses()
    today = timezone.localdate()
    # Fetch today's attendance record
    attendance = Attendance.objects.filter(user=request.user, date=today).first()
    
    # Recent history (past 10 days)
    recent_attendance = Attendance.objects.filter(user=request.user).order_by('-date')[:10]
    
    is_owner_or_manager = is_manager_or_owner(request.user)
    
    context = {
        'attendance': attendance,
        'recent_attendance': recent_attendance,
        'today': today,
        'is_owner_or_manager': is_owner_or_manager,
    }
    
    if is_owner_or_manager:
        # Fetch Admin/Manager Overview Statistics
        branches = request.user.get_accessible_branches()
        branch_users = User.objects.filter(
            Q(branches__in=branches) | Q(active_branch__in=branches)
        ).distinct()
        if is_owner(request.user):
            branch_users = User.objects.all()
            
        total_staff_count = branch_users.count()
        
        # Today's checkins
        today_records = Attendance.objects.filter(date=today)
        if not is_owner(request.user):
            today_records = today_records.filter(
                Q(branch__in=branches) | Q(user__branches__in=branches) | Q(user__active_branch__in=branches)
            ).distinct()
            
        checked_in_count = today_records.filter(check_in__isnull=False).count()
        late_count = today_records.filter(status='late').count()
        half_day_count = today_records.filter(status='half_day').count()
        leave_count = today_records.filter(status='on_leave').count()
        absent_count = total_staff_count - (checked_in_count + leave_count)
        if absent_count < 0:
            absent_count = 0
            
        # Pending approvals - ONLY FOR ADMIN (OWNER)
        pending_leaves = LeaveRequest.objects.none()
        if is_owner(request.user):
            pending_permissions = PermissionRequest.objects.filter(status='pending')
        else:
            pending_permissions = PermissionRequest.objects.none()
            
        context.update({
            'total_staff_count': total_staff_count,
            'checked_in_count': checked_in_count,
            'late_count': late_count,
            'half_day_count': half_day_count,
            'leave_count': leave_count,
            'absent_count': absent_count,
            'pending_leaves_count': pending_leaves.count(),
            'pending_permissions_count': pending_permissions.count(),
            'pending_leaves': pending_leaves[:5],
            'pending_permissions': pending_permissions[:5],
        })
    else:
        # Fetch Staff Personal Dashboard Statistics (for current month)
        start_of_month = today.replace(day=1)
        personal_month_atts = Attendance.objects.filter(
            user=request.user, 
            date__range=(start_of_month, today)
        )
        
        present_cnt = personal_month_atts.filter(status='present').count()
        late_cnt = personal_month_atts.filter(status='late').count()
        half_day_cnt = personal_month_atts.filter(status='half_day').count()
        leave_cnt = personal_month_atts.filter(status='on_leave').count()
        
        # Calculate absent days in this month up to today
        total_days_passed = (today - start_of_month).days + 1
        recorded_days = personal_month_atts.count()
        
        unrecorded_leaves = 0
        
        absent_cnt = total_days_passed - recorded_days - unrecorded_leaves
        if absent_cnt < 0:
            absent_cnt = 0
            
        # Recent personal payslips
        payslips = MonthlyPayroll.objects.filter(user=request.user).order_by('-year', '-month')[:6]
        
        # Salary config
        sal_config = SalaryConfig.objects.filter(user=request.user).first()
        
        context.update({
            'present_cnt': present_cnt,
            'late_cnt': late_cnt,
            'half_day_cnt': half_day_cnt,
            'leave_cnt': leave_cnt,
            'absent_cnt': absent_cnt,
            'payslips': payslips,
            'sal_config': sal_config,
        })
        
    return render(request, 'attendance/dashboard.html', context)

@login_required
def check_in(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            photo_data = data.get('photo')
            lat = data.get('lat')
            lng = data.get('lng')
            
            today = timezone.localdate()
            
            # Check if already checked in
            existing = Attendance.objects.filter(user=request.user, date=today).first()
            if existing and existing.check_in:
                return JsonResponse({'success': False, 'message': 'Already checked in for today.'})
            
            # Parse photo file
            photo_file = get_file_from_base64(photo_data, f"{request.user.username}_checkin_{today}")
            if not photo_file:
                return JsonResponse({'success': False, 'message': 'Photo capture is required.'})
            
            # Check if user has active branch
            branch = request.user.active_branch
            if not branch:
                # If active_branch is not set, use the first branch assigned to them
                branch = request.user.branches.first()
                if not branch:
                    return JsonResponse({'success': False, 'message': 'No branch assigned to user. Please contact admin.'})
            
            # Check-in time threshold for late mark (using user's specific shift and grace period)
            now = timezone.localtime(timezone.now())
            # Tiered late / half-day / absent status evaluation
            shift_start = request.user.shift_start_time
            global_policy = GlobalPermissionPolicy.get_policy()
            grace_mins = global_policy.grace_period_minutes
            
            local_shift_datetime = timezone.make_aware(
                datetime.datetime.combine(today, shift_start),
                timezone.get_current_timezone()
            )
            
            delay_minutes = (now - local_shift_datetime).total_seconds() / 60.0

            status = 'checked_in'
            on_leave = False
            if on_leave:
                status = 'on_leave'

            if existing:
                existing.check_in = timezone.now()
                existing.check_in_photo = photo_file
                existing.check_in_lat = lat
                existing.check_in_lng = lng
                existing.status = status
                existing.save()
                att = existing
            else:
                att = Attendance.objects.create(
                    user=request.user,
                    branch=branch,
                    date=today,
                    check_in=timezone.now(),
                    check_in_photo=photo_file,
                    check_in_lat=lat,
                    check_in_lng=lng,
                    status=status
                )
                
            return JsonResponse({
                'success': True, 
                'message': 'Checked in successfully!', 
                'status': att.status,
                'time': timezone.localtime(att.check_in).strftime('%I:%M %p')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})

@login_required
def mid_day_check(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            photo_data = data.get('photo')
            lat = data.get('lat')
            lng = data.get('lng')
            
            today = timezone.localdate()
            
            # Fetch existing attendance record
            attendance = Attendance.objects.filter(user=request.user, date=today).first()
            if not attendance:
                return JsonResponse({'success': False, 'message': 'Please check-in first before mid-day verification.'})
            
            if attendance.mid_day_time:
                return JsonResponse({'success': False, 'message': 'Mid-day verification already completed.'})
            
            photo_file = get_file_from_base64(photo_data, f"{request.user.username}_midday_{today}")
            if not photo_file:
                return JsonResponse({'success': False, 'message': 'Photo capture is required.'})
                
            attendance.mid_day_time = timezone.now()
            attendance.mid_day_photo = photo_file
            attendance.mid_day_lat = lat
            attendance.mid_day_lng = lng
            attendance.save()
            
            return JsonResponse({
                'success': True, 
                'message': 'Mid-day verification completed successfully!', 
                'time': timezone.localtime(attendance.mid_day_time).strftime('%I:%M %p')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})

@login_required
def check_out(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            photo_data = data.get('photo')
            lat = data.get('lat')
            lng = data.get('lng')
            
            today = timezone.localdate()
            
            # Fetch existing attendance record
            attendance = Attendance.objects.filter(user=request.user, date=today).first()
            if not attendance:
                return JsonResponse({'success': False, 'message': 'Please check-in first before checking out.'})
            
            if attendance.check_out:
                return JsonResponse({'success': False, 'message': 'Already checked out for today.'})
            
            photo_file = get_file_from_base64(photo_data, f"{request.user.username}_checkout_{today}")
            if not photo_file:
                return JsonResponse({'success': False, 'message': 'Photo capture is required.'})
                
            now_dt = timezone.now()
            attendance.check_out = now_dt
            attendance.check_out_photo = photo_file
            attendance.check_out_lat = lat
            attendance.check_out_lng = lng

            # Automatically calculate attendance status based on shift & worked duration
            attendance.recalculate_status()
            attendance.save()
            
            return JsonResponse({
                'success': True, 
                'message': 'Checked out successfully!', 
                'time': timezone.localtime(attendance.check_out).strftime('%I:%M %p')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


# --- Leave Views (Disabled) ---

@login_required
def leave_list(request):
    raise Http404("Leave management is disabled.")

@login_required
def leave_request(request):
    raise Http404("Leave management is disabled.")

@login_required
def leave_approve(request, pk, action):
    raise Http404("Leave management is disabled.")


# --- Permission Views ---

@login_required
def permission_list(request):
    user = request.user
    my_permissions = PermissionRequest.objects.filter(user=user).order_by('-created_at')
    
    pending_perms = []
    past_perms_page = None
    
    # Get user's accessible branches
    branches = user.get_accessible_branches()
    
    # Filter variables for past permissions
    q_perm = request.GET.get('q_perm', '').strip()
    branch_perm = request.GET.get('branch_perm', '').strip()
    
    if is_owner(user):
        pending_perms = PermissionRequest.objects.filter(status='pending').exclude(user=user).select_related('user', 'approved_by')
        past_perms_qs = PermissionRequest.objects.exclude(status='pending').exclude(user=user).select_related('user', 'approved_by')
    else:
        pending_perms = []
        past_perms_qs = PermissionRequest.objects.none()

    # Apply search/filters
    if q_perm:
        past_perms_qs = past_perms_qs.filter(
            Q(user__username__icontains=q_perm) | Q(user__employee_id__icontains=q_perm)
        )
    if branch_perm:
        past_perms_qs = past_perms_qs.filter(user__branches__id=branch_perm)
        
    past_perms_qs = past_perms_qs.order_by('-created_at')
    
    # Pagination for past permissions
    from django.core.paginator import Paginator
    paginator = Paginator(past_perms_qs, 10)
    page_number = request.GET.get('page')
    past_perms_page = paginator.get_page(page_number)
    
    # Load global permission policy limits
    global_policy = GlobalPermissionPolicy.get_policy()
    max_permissions = global_policy.max_permissions_per_month
    max_hours = global_policy.max_hours_per_permission

    # Count how many permissions the user has requested/approved in the current month (excluding rejected)
    today_date = timezone.localdate()
    _, last_day = calendar.monthrange(today_date.year, today_date.month)
    current_month_start = today_date.replace(day=1).strftime('%Y-%m-%d')
    current_month_end = today_date.replace(day=last_day).strftime('%Y-%m-%d')
    current_month_name = today_date.strftime('%B %Y')

    permissions_used_this_month = PermissionRequest.objects.filter(
        user=user,
        date__year=today_date.year,
        date__month=today_date.month
    ).exclude(status='rejected').count()
        
    context = {
        'my_permissions': my_permissions,
        'pending_perms': pending_perms,
        'past_perms': past_perms_page,
        'branches': branches,
        'q_perm': q_perm,
        'selected_branch_id': branch_perm,
        'global_policy': global_policy,
        'max_permissions': max_permissions,
        'max_hours': max_hours,
        'permissions_used_this_month': permissions_used_this_month,
        'current_month_start': current_month_start,
        'current_month_end': current_month_end,
        'current_month_name': current_month_name,
        'is_owner': is_owner(user),
        'is_owner_or_manager': is_manager_or_owner(user),
    }
    return render(request, 'attendance/permission_list.html', context)

@login_required
def update_global_permission_policy(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized access: Admin privilege required.')
        return redirect('attendance:permission_list')
        
    if request.method == 'POST':
        try:
            max_perms = int(request.POST.get('max_permissions_per_month', 2))
            max_hours = Decimal(request.POST.get('max_hours_per_permission', '2.00'))
            grace_mins = int(request.POST.get('grace_period_minutes', 15))
            late_thresh = int(request.POST.get('late_threshold_for_half_day_deduction', 1))
            
            if max_perms < 1:
                messages.error(request, 'Max permissions per month must be at least 1.')
                return redirect('attendance:permission_list')
            if max_hours <= 0:
                messages.error(request, 'Max hours per permission must be greater than 0.')
                return redirect('attendance:permission_list')
            if grace_mins < 0:
                messages.error(request, 'Grace period minutes cannot be negative.')
                return redirect('attendance:permission_list')
            if late_thresh < 1:
                messages.error(request, 'Late threshold must be at least 1.')
                return redirect('attendance:permission_list')
                
            policy = GlobalPermissionPolicy.get_policy()
            policy.max_permissions_per_month = max_perms
            policy.max_hours_per_permission = max_hours
            policy.grace_period_minutes = grace_mins
            policy.late_threshold_for_half_day_deduction = late_thresh
            policy.updated_by = request.user
            policy.save()
            
            # Sync all User objects so global grace period applies everywhere
            User.objects.all().update(grace_period_minutes=grace_mins)
            
            # Sync all SalaryConfig objects so that user defaults stay aligned
            SalaryConfig.objects.all().update(
                max_permissions_per_month=max_perms,
                max_hours_per_permission=max_hours
            )
            
            from .models import format_duration_display
            policy_dur_str = format_duration_display(max_hours)
            
            messages.success(
                request,
                f'Global policy updated! Grace period: {grace_mins} mins, {max_perms} perms/month ({policy_dur_str} max), {late_thresh} Lates = 0.5 Day Cut.'
            )
        except Exception as e:
            messages.error(request, f'Failed to update global permission policy: {e}')
            
    return redirect('attendance:permission_list')

@login_required
def permission_request(request):
    if request.method == 'POST':
        date_str = request.POST.get('date')
        start_time_str = request.POST.get('start_time')
        end_time_str = request.POST.get('end_time')
        reason = request.POST.get('reason')
        
        try:
            date_val = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time = datetime.datetime.strptime(start_time_str, '%H:%M').time()
            end_time = datetime.datetime.strptime(end_time_str, '%H:%M').time()
            
            # 0. Validate that date is within current month
            today_date = timezone.localdate()
            if date_val.year != today_date.year or date_val.month != today_date.month:
                messages.error(
                    request,
                    f'Failed to submit request: Permission can only be applied for dates within the current month ({today_date.strftime("%B %Y")}).'
                )
                return redirect('attendance:permission_list')

            # 1. Calculate duration and validate hourly limit
            start_dt = datetime.datetime.combine(date_val, start_time)
            end_dt = datetime.datetime.combine(date_val, end_time)
            if end_dt <= start_dt:
                messages.error(request, 'Failed to submit request: End time must be after start time.')
                return redirect('attendance:permission_list')
                
            duration_hours = Decimal(str((end_dt - start_dt).total_seconds() / 3600.0))
            
            global_policy = GlobalPermissionPolicy.get_policy()
            max_hours = global_policy.max_hours_per_permission
            max_perms = global_policy.max_permissions_per_month
                
            if duration_hours > max_hours:
                from .models import format_duration_display
                req_dur_str = format_duration_display(duration_hours)
                limit_dur_str = format_duration_display(max_hours)
                messages.error(
                    request,
                    f'Failed to submit request: Duration ({req_dur_str}) '
                    f'exceeds your permitted limit of {limit_dur_str} per request.'
                )
                return redirect('attendance:permission_list')
                
            # 2. Validate monthly quota limit (excluding rejected)
            existing_perms_count = PermissionRequest.objects.filter(
                user=request.user,
                date__year=date_val.year,
                date__month=date_val.month
            ).exclude(status='rejected').count()
            
            if existing_perms_count >= max_perms:
                messages.error(
                    request,
                    f'Failed to submit request: You have already used your quota of '
                    f'{existing_perms_count} / {max_perms} permissions for the month of {date_val.strftime("%B %Y")}.'
                )
                return redirect('attendance:permission_list')
            
            PermissionRequest.objects.create(
                user=request.user,
                date=date_val,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                status='pending'
            )
            messages.success(request, 'Short permission request submitted successfully.')
        except ValueError as e:
            messages.error(request, f'Invalid date or time formats: {e}')
        except Exception as e:
            messages.error(request, f'Failed to submit permission request: {e}')
            
        return redirect('attendance:permission_list')
    return redirect('attendance:permission_list')

@login_required
def permission_approve(request, pk, action):
    next_url = request.GET.get('next') or request.POST.get('next') or request.META.get('HTTP_REFERER') or 'attendance:permission_list'
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1'
    
    if not is_owner(request.user):
        msg = 'Unauthorized access. Only Admin can approve or reject permission requests.'
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=403)
        messages.error(request, msg)
        return redirect(next_url)
        
    perm = get_object_or_404(PermissionRequest, pk=pk)
            
    try:
        if action == 'approve':
            perm.status = 'approved'
            perm.approved_by = request.user
            perm.save()
            msg = f'Permission for {perm.user.username} approved.'
            if not is_ajax:
                messages.success(request, msg)
        elif action == 'reject':
            perm.status = 'rejected'
            perm.approved_by = request.user
            perm.save()
            msg = f'Permission for {perm.user.username} rejected.'
            if not is_ajax:
                messages.success(request, msg)
        else:
            msg = 'Invalid action.'
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect(next_url)

        if is_ajax:
            return JsonResponse({'success': True, 'action': action, 'message': msg, 'pk': pk})
    except Exception as e:
        msg = f'Error processing permission approval: {e}'
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg}, status=500)
        messages.error(request, msg)
        
    return redirect(next_url)


# --- Reports Views ---

@login_required
def attendance_reports(request):
    auto_update_past_attendance_statuses()
    if not is_manager_or_owner(request.user):
        messages.error(request, 'Unauthorized access.')
        return redirect('attendance:dashboard')
        
    branches = request.user.get_accessible_branches()
    users = User.objects.filter(
        Q(branches__in=branches) | Q(active_branch__in=branches)
    ).distinct()
    
    if is_owner(request.user):
        users = User.objects.all()
    users = users.order_by('employee_id', 'username')
        
    # Filters for detailed list logs
    selected_branch = request.GET.get('branch', '')
    selected_user = request.GET.get('user', '')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    active_tab = request.GET.get('tab', 'grid')
    
    today = timezone.localdate()
    start_date = today - datetime.timedelta(days=30)
    end_date = today
    
    if start_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
            
    records = Attendance.objects.filter(date__range=(start_date, end_date)).select_related('user', 'branch')
    
    if not is_owner(request.user):
        records = records.filter(
            Q(branch__in=branches) | Q(user__branches__in=branches) | Q(user__active_branch__in=branches)
        ).distinct()
        
    if selected_branch:
        records = records.filter(branch_id=selected_branch)
    if selected_user:
        records = records.filter(user_id=selected_user)
        
    records = records.order_by('-date', 'user__employee_id', 'user__username')
    
    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="attendance_report_{start_date}_{end_date}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Employee ID', 'Username', 'Branch', 'Check In', 'Check Out', 'Mid Day Check', 'Status', 'Notes'])
        
        for r in records:
            check_in_time = timezone.localtime(r.check_in).strftime('%I:%M %p') if r.check_in else '-'
            check_out_time = timezone.localtime(r.check_out).strftime('%I:%M %p') if r.check_out else '-'
            mid_day = timezone.localtime(r.mid_day_time).strftime('%I:%M %p') if r.mid_day_time else '-'
            branch_name = r.branch.name if r.branch else ''
            writer.writerow([
                r.date, 
                r.user.employee_id or '', 
                r.user.username, 
                branch_name, 
                check_in_time, 
                check_out_time, 
                mid_day, 
                r.get_status_display(), 
                r.notes or ''
            ])
        return response

    # Pagination for detailed daily logs
    from django.core.paginator import Paginator
    paginator = Paginator(records, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # --- Visual Monthly Grid Builder ---
    grid_month = int(request.GET.get('grid_month', today.month))
    grid_year = int(request.GET.get('grid_year', today.year))
    
    # Build list of days for this month
    days_in_month = calendar.monthrange(grid_year, grid_month)[1]
    day_numbers = list(range(1, days_in_month + 1))
    
    # Filter users based on selected branch/user if any
    grid_users_qs = users.order_by('employee_id', 'username')
    if selected_branch:
        grid_users_qs = grid_users_qs.filter(branches__id=selected_branch).distinct()
    if selected_user:
        grid_users_qs = grid_users_qs.filter(id=selected_user)

    grid_users = list(grid_users_qs)
    grid_users.sort(key=lambda u: (u.employee_id or '', u.username or ''))
    grid_user_ids = [u.id for u in grid_users]

    # Bulk fetch ALL Attendance records for this grid month
    all_grid_atts = Attendance.objects.filter(
        user_id__in=grid_user_ids,
        date__year=grid_year,
        date__month=grid_month
    )
    atts_dict = {(att.user_id, att.date.day): att for att in all_grid_atts}

    all_grid_leaves = []
    leave_dict = {}

    grid_data = []
    for u in grid_users:
        u_days = []
        p_cnt = 0
        l_cnt = 0
        a_cnt = 0
        lv_cnt = 0
        h_cnt = 0
        
        user_leaves = leave_dict.get(u.id, [])

        wo_cnt = 0
        allowed_offs = u.monthly_off_count or 4
        for d in day_numbers:
            d_date = datetime.date(grid_year, grid_month, d)
            status = ''
            rec_id = None
            notes = ''
            
            att = atts_dict.get((u.id, d))
            if att:
                status = att.status
                rec_id = att.id
                notes = att.notes or ''
                if status == 'present': p_cnt += 1
                elif status == 'late': l_cnt += 1
                elif status == 'half_day': h_cnt += 1
                elif status == 'on_leave': lv_cnt += 1
                elif status == 'week_off': wo_cnt += 1
                elif status == 'absent': a_cnt += 1
            else:
                if d_date > today:
                    status = 'future'
                else:
                    leave_match = next((reason for sdate, edate, reason in user_leaves if sdate <= d_date <= edate), None)
                    if leave_match is not None:
                        status = 'on_leave'
                        notes = leave_match or 'Approved Leave'
                        lv_cnt += 1
                    else:
                        if wo_cnt < allowed_offs:
                            status = 'week_off'
                            wo_cnt += 1
                        else:
                            status = 'absent'
                            a_cnt += 1
            
            u_days.append({
                'day': d,
                'status': status,
                'record_id': rec_id,
                'notes': notes
            })
            
        grid_data.append({
            'user': u,
            'days': u_days,
            'summary': {
                'present': p_cnt,
                'late': l_cnt,
                'absent': a_cnt,
                'leave': lv_cnt,
                'half_day': h_cnt,
                'week_off': wo_cnt,
            }
        })
        
    # Grid CSV Export
    if request.GET.get('export') == 'grid_csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="monthly_attendance_grid_{grid_month}_{grid_year}.csv"'
        writer = csv.writer(response)
        
        header = ['Employee ID', 'Employee Name', 'Username', 'Branch'] + [f"Day {d}" for d in day_numbers] + ['Present (P)', 'Late (L)', 'Half Day (H)', 'Leave (V)', 'Absent (A)']
        writer.writerow(header)
        
        status_map = {
            'checked_in': 'IN',
            'present': 'P',
            'late': 'L',
            'half_day': 'H',
            'on_leave': 'V',
            'absent': 'A',
            'future': '-'
        }
        
        for item in grid_data:
            u = item['user']
            emp_name = f"{u.first_name} {u.last_name}".strip() or u.username
            branches_str = ", ".join([b.name for b in u.branches.all()]) if u.branches.exists() else ''
            
            day_cols = [status_map.get(d['status'], '-') for d in item['days']]
            summary = item['summary']
            
            row = [
                u.employee_id or '',
                emp_name,
                u.username,
                branches_str
            ] + day_cols + [
                summary['present'],
                summary['late'],
                summary['half_day'],
                summary['leave'],
                summary['absent']
            ]
            writer.writerow(row)
            
        return response
        
    # Audit logs for history
    audit_q = request.GET.get('audit_q', '').strip()
    audit_logs_qs = AttendanceAuditLog.objects.select_related('attendance', 'attendance__user', 'attendance__branch', 'edited_by').order_by('-timestamp')
    if selected_branch:
        audit_logs_qs = audit_logs_qs.filter(attendance__branch_id=selected_branch)
    if start_date_str:
        audit_logs_qs = audit_logs_qs.filter(attendance__date__gte=start_date)
    if end_date_str:
        audit_logs_qs = audit_logs_qs.filter(attendance__date__lte=end_date)
    if audit_q:
        audit_logs_qs = audit_logs_qs.filter(
            Q(attendance__user__first_name__icontains=audit_q) |
            Q(attendance__user__last_name__icontains=audit_q) |
            Q(attendance__user__username__icontains=audit_q) |
            Q(attendance__user__employee_id__icontains=audit_q) |
            Q(edited_by__first_name__icontains=audit_q) |
            Q(edited_by__last_name__icontains=audit_q) |
            Q(edited_by__username__icontains=audit_q) |
            Q(edited_by__employee_id__icontains=audit_q)
        ).distinct()

    if request.GET.get('export') == 'audit_csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="attendance_audit_logs_{today}.csv"'
        writer = csv.writer(response)
        
        writer.writerow([
            'Timestamp', 'Employee ID', 'Employee Name', 'Username', 'Attendance Date', 'Branch', 'Edited By', 
            'Old Status', 'New Status', 
            'Old Check-In Time', 'New Check-In Time', 
            'Old Check-Out Time', 'New Check-Out Time', 
            'Correction Notes'
        ])
        
        for log in audit_logs_qs:
            u = log.attendance.user
            emp_name = f"{u.first_name} {u.last_name}".strip() or u.username
            branch_name = log.attendance.branch.name if log.attendance.branch else ''
            edited_by = log.edited_by.username if log.edited_by else 'System'
            edited_time = timezone.localtime(log.timestamp).strftime('%Y-%m-%d %I:%M %p') if log.timestamp else ''
            
            old_in = log.old_check_in_time.strftime('%I:%M %p') if log.old_check_in_time else '-'
            new_in = log.new_check_in_time.strftime('%I:%M %p') if log.new_check_in_time else '-'
            old_out = log.old_check_out_time.strftime('%I:%M %p') if log.old_check_out_time else '-'
            new_out = log.new_check_out_time.strftime('%I:%M %p') if log.new_check_out_time else '-'
            
            writer.writerow([
                edited_time,
                u.employee_id or '',
                emp_name,
                u.username,
                log.attendance.date,
                branch_name,
                edited_by,
                log.old_status or 'absent',
                log.new_status,
                old_in,
                new_in,
                old_out,
                new_out,
                log.notes or ''
            ])
            
        return response
        
    # Audit logs pagination
    audit_paginator = Paginator(audit_logs_qs, 20)
    audit_page_number = request.GET.get('audit_page', 1)
    audit_page_obj = audit_paginator.get_page(audit_page_number)
        
    context = {
        'page_obj': page_obj,  # paginated page object
        'audit_page_obj': audit_page_obj, # paginated audit logs object
        'branches': branches,
        'users': users,
        'selected_branch': selected_branch,
        'selected_user': selected_user,
        'audit_q': audit_q,
        'start_date_val': start_date.strftime('%Y-%m-%d'),
        'end_date_val': end_date.strftime('%Y-%m-%d'),
        'active_tab': active_tab,
        
        # Grid parameters
        'grid_data': grid_data,
        'day_numbers': day_numbers,
        'grid_month': grid_month,
        'grid_year': grid_year,
        'months': range(1, 13),
        'years': range(today.year - 2, today.year + 2),
        'is_owner': is_owner(request.user),
    }
    return render(request, 'attendance/reports.html', context)


# --- Salary/Payroll Views ---

@login_required
def salary_list(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized access to salary configs.')
        return redirect('attendance:dashboard')
        
    users = User.objects.all().order_by('username')
    existing_config_user_ids = set(SalaryConfig.objects.values_list('user_id', flat=True))
    missing_users = [u for u in users if u.id not in existing_config_user_ids]
    if missing_users:
        SalaryConfig.objects.bulk_create([SalaryConfig(user=u, monthly_base_salary=Decimal('0.00')) for u in missing_users])
        
    q_staff = request.GET.get('q_staff', '').strip()
    branch_staff = request.GET.get('branch_staff', '').strip()
    
    if q_staff:
        users = users.filter(Q(username__icontains=q_staff) | Q(employee_id__icontains=q_staff) | Q(first_name__icontains=q_staff) | Q(last_name__icontains=q_staff))
    if branch_staff:
        users = users.filter(branches__id=branch_staff)
        
    users = users.distinct()
    branches = Branch.objects.all().order_by('name')
    
    today = timezone.localdate()
    
    global_policy = GlobalPermissionPolicy.get_policy()
    
    context = {
        'users': users,
        'branches': branches,
        'q_staff': q_staff,
        'selected_branch_id': branch_staff,
        'months': range(1, 13),
        'years': range(today.year - 2, today.year + 2),
        'current_month': today.month,
        'current_year': today.year,
        'global_policy': global_policy,
    }
    return render(request, 'attendance/payroll.html', context)


def ensure_monthly_payrolls(month, year, request_user=None, force_recalculate=True):
    if force_recalculate:
        # Process users whose payroll is missing or still in 'draft'
        paid_user_ids = set(MonthlyPayroll.objects.filter(month=month, year=year, status='paid').values_list('user_id', flat=True))
        users_to_process = list(User.objects.exclude(id__in=paid_user_ids).order_by('username'))
    else:
        existing_user_ids = set(MonthlyPayroll.objects.filter(month=month, year=year).values_list('user_id', flat=True))
        users_to_process = list(User.objects.exclude(id__in=existing_user_ids).order_by('username'))

    if not users_to_process:
        return

    first_day = datetime.date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = datetime.date(year, month, days_in_month)
    proc_user_ids = [u.id for u in users_to_process]

    # 1. Bulk get or create SalaryConfigs
    salary_configs = {sc.user_id: sc for sc in SalaryConfig.objects.filter(user_id__in=proc_user_ids)}
    new_configs = []
    for u in users_to_process:
        if u.id not in salary_configs:
            new_configs.append(SalaryConfig(user=u, monthly_base_salary=Decimal('0.00')))
    if new_configs:
        SalaryConfig.objects.bulk_create(new_configs)
        salary_configs = {sc.user_id: sc for sc in SalaryConfig.objects.filter(user_id__in=proc_user_ids)}

    # 2. Bulk fetch Attendance records into dictionary: {(user_id, date): att_obj}
    all_att = Attendance.objects.filter(user_id__in=proc_user_ids, date__range=(first_day, last_day))
    att_dict = {(att.user_id, att.date): att for att in all_att}

    # 3. Bulk fetch Approved Permission dates into dictionary: {user_id: set(dates)}
    all_perms = PermissionRequest.objects.filter(
        user_id__in=proc_user_ids,
        date__range=(first_day, last_day),
        status='approved'
    ).values_list('user_id', 'date')
    perm_dict = {}
    for uid, pdate in all_perms:
        perm_dict.setdefault(uid, set()).add(pdate)

    global_policy = GlobalPermissionPolicy.get_policy()
    late_thresh = max(1, global_policy.late_threshold_for_half_day_deduction or 1)

    for user in users_to_process:
        config = salary_configs.get(user.id)
        base_salary = config.monthly_base_salary if config else Decimal('0.00')

        user_perm_dates = perm_dict.get(user.id, set())

        present_days = 0
        absent_days = 0
        late_days = 0
        approved_leaves = 0
        unapproved_leaves = 0

        current_date = first_day
        while current_date <= last_day:
            att_rec = att_dict.get((user.id, current_date))

            if att_rec:
                if att_rec.status in ['present', 'checked_in']:
                    present_days += 1
                elif att_rec.status == 'late':
                    if current_date not in user_perm_dates:
                        late_days += 1
                    present_days += 1
                elif att_rec.status == 'half_day':
                    present_days += 0.5
                    absent_days += 0.5
                else:
                    absent_days += 1
                    unapproved_leaves += 1
            else:
                absent_days += 1
                unapproved_leaves += 1

            current_date += datetime.timedelta(days=1)

        allowed_offs = getattr(user, 'monthly_off_count', 4)
        if present_days == 0:
            lop_days_to_deduct = Decimal(str(unapproved_leaves))
        else:
            lop_days_to_deduct = Decimal(str(max(0, unapproved_leaves - allowed_offs)))
        per_day_rate = base_salary / Decimal(str(days_in_month)) if days_in_month > 0 else Decimal('0')
        half_day_rate = per_day_rate / Decimal('2')

        lop_deduction = lop_days_to_deduct * per_day_rate
        late_half_days = Decimal(str(late_days // late_thresh))
        late_deduction = late_half_days * half_day_rate

        total_deductions = late_deduction + lop_deduction
        net_salary = max(Decimal('0.00'), base_salary - total_deductions)
        MonthlyPayroll.objects.update_or_create(
            user=user,
            month=month,
            year=year,
            defaults={
                'present_days': Decimal(str(present_days)),
                'absent_days': Decimal(str(absent_days)),
                'late_days': late_days,
                'approved_leaves': approved_leaves,
                'unapproved_leaves': unapproved_leaves,
                'base_salary': base_salary,
                'deductions': total_deductions,
                'net_salary': net_salary,
                'processed_by': request_user if (request_user and request_user.is_authenticated) else None,
                'status': 'draft',
            }
        )


@login_required
def pay_slips_view(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized access.')
        return redirect('attendance:dashboard')
        
    today = timezone.localdate()
    selected_month = int(request.GET.get('month', today.month))
    selected_year = int(request.GET.get('year', today.year))
    
    # Auto-ensure monthly payroll records exist for all users
    ensure_monthly_payrolls(selected_month, selected_year, request.user, force_recalculate=True)
    
    raw_month_payrolls = MonthlyPayroll.objects.filter(month=selected_month, year=selected_year).select_related('user')
    
    aggs = raw_month_payrolls.aggregate(
        base=Sum('base_salary'),
        deductions=Sum('deductions'),
        net=Sum('net_salary'),
        paid=Count('id', filter=Q(status='paid')),
        draft=Count('id', filter=Q(status='draft')),
        total=Count('id')
    )
    total_base = aggs['base'] or Decimal('0.00')
    total_deductions = aggs['deductions'] or Decimal('0.00')
    total_net = aggs['net'] or Decimal('0.00')
    paid_count = aggs['paid'] or 0
    draft_count = aggs['draft'] or 0
    total_staff_payrolls = aggs['total'] or 0

    payrolls = raw_month_payrolls
    q_payroll = request.GET.get('q_payroll', '').strip()
    branch_payroll = request.GET.get('branch_payroll', '').strip()
    status_payroll = request.GET.get('status_payroll', '').strip()

    if q_payroll:
        payrolls = payrolls.filter(
            Q(user__username__icontains=q_payroll) | 
            Q(user__employee_id__icontains=q_payroll) |
            Q(user__first_name__icontains=q_payroll) |
            Q(user__last_name__icontains=q_payroll)
        )
    if branch_payroll:
        payrolls = payrolls.filter(user__branches__id=branch_payroll)
    if status_payroll and status_payroll in ['draft', 'paid']:
        payrolls = payrolls.filter(status=status_payroll)

    payrolls = payrolls.distinct().order_by('user__employee_id', 'user__username')

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="pay_slips_{selected_month}_{selected_year}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Employee ID', 'Username', 'Full Name', 'Month', 'Year',
            'Present Days', 'Late Days', 'LOP Days',
            'Base Salary (Rs)', 'Late Cut (Rs)', 'Total Deductions (Rs)', 'Net Salary (Rs)', 'Status'
        ])
        for p in payrolls:
            emp_id = getattr(p.user, 'employee_id', None) or p.user.id
            full_name = p.user.get_full_name() or p.user.username
            writer.writerow([
                emp_id,
                p.user.username,
                full_name,
                p.month,
                p.year,
                p.present_days,
                p.late_days,
                p.lop_days,
                f"{p.base_salary:.2f}",
                f"{p.late_deduction_amount:.2f}",
                f"{p.deductions:.2f}",
                f"{p.net_salary:.2f}",
                p.status.upper()
            ])
        return response

    branches = Branch.objects.all().order_by('name')
    
    context = {
        'payrolls': payrolls,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': range(1, 13),
        'years': range(today.year - 2, today.year + 2),
        'branches': branches,
        'q_payroll': q_payroll,
        'branch_payroll': branch_payroll,
        'status_payroll': status_payroll,
        'total_base': total_base,
        'total_deductions': total_deductions,
        'total_net': total_net,
        'paid_count': paid_count,
        'draft_count': draft_count,
        'total_staff_payrolls': total_staff_payrolls,
    }
    return render(request, 'attendance/pay_slips.html', context)

@login_required
def salary_config_view(request, user_id):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized access.')
        return redirect('attendance:dashboard')
        
    user_obj = get_object_or_404(User, pk=user_id)
    config, created = SalaryConfig.objects.get_or_create(user=user_obj)
    
    if request.method == 'POST':
        try:
            base = request.POST.get('monthly_base_salary', '0')
            config.monthly_base_salary = Decimal(base)
            config.save()
            
            messages.success(request, f'Monthly Base Salary updated for {user_obj.username}.')
            return redirect('attendance:payroll_list')
        except (ValueError, TypeError, Exception) as e:
            messages.error(request, f'Failed to update configuration: {e}')
        
    context = {
        'employee': user_obj,
        'config': config,
    }
    return render(request, 'attendance/salary_config.html', context)

@login_required
def generate_payroll(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized.')
        return redirect('attendance:dashboard')
        
    if request.method == 'POST':
        try:
            month = int(request.POST.get('month'))
            year = int(request.POST.get('year'))
            
            ensure_monthly_payrolls(month, year, request.user, force_recalculate=True)
            
            count = MonthlyPayroll.objects.filter(month=month, year=year).count()
            messages.success(request, f"Payroll generated successfully for all {count} staff members.")
            return redirect(f"{reverse('attendance:pay_slips')}?month={month}&year={year}")
        except Exception as e:
            messages.error(request, f"Error generating payroll: {e}")
            return redirect('attendance:pay_slips')
            
    return redirect('attendance:pay_slips')

@login_required
def mark_payroll_paid(request, payroll_id):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized.')
        return redirect('attendance:dashboard')
        
    payroll = get_object_or_404(MonthlyPayroll, pk=payroll_id)
    payroll.status = 'paid'
    payroll.save()
    messages.success(request, f"Salary of Rs.{payroll.net_salary} for {payroll.user.username} marked as PAID.")
    return redirect(f"{reverse('attendance:pay_slips')}?month={payroll.month}&year={payroll.year}")

@login_required
def mark_all_payrolls_paid(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized.')
        return redirect('attendance:dashboard')
        
    if request.method == 'POST':
        month = request.POST.get('month')
        year = request.POST.get('year')
        if month and year:
            updated_count = MonthlyPayroll.objects.filter(
                month=month,
                year=year,
                status='draft'
            ).update(status='paid')
            
            messages.success(request, f"Successfully marked all {updated_count} draft pay slips as PAID for {month}/{year}.")
            return redirect(f"{reverse('attendance:pay_slips')}?month={month}&year={year}")
            
    return redirect('attendance:pay_slips')

@login_required
def edit_attendance_ajax(request, pk):
    if not is_owner(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized access. Only Admin can edit attendance records.'})
        
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            status = data.get('status')
            notes = data.get('notes', '')
            user_id = data.get('user_id')
            date_str = data.get('date')
            check_in_time_str = data.get('check_in_time')
            check_out_time_str = data.get('check_out_time')
            
            old_status = None
            if pk and int(pk) > 0:
                att = get_object_or_404(Attendance, pk=pk)
                old_status = att.status
            else:
                if not user_id or not date_str:
                    return JsonResponse({'success': False, 'message': 'User ID and Date are required for creating new attendance entries.'})
                target_user = get_object_or_404(User, pk=user_id)
                att_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                branch = target_user.active_branch or target_user.branches.first()
                if not branch:
                    from core.models import Branch
                    branch = Branch.objects.first()
                att, created = Attendance.objects.get_or_create(
                    user=target_user,
                    date=att_date,
                    defaults={'branch': branch}
                )
                old_status = 'absent' if created else att.status

            old_in_t_obj = timezone.localtime(att.check_in).time() if att.check_in else None
            old_out_t_obj = timezone.localtime(att.check_out).time() if att.check_out else None
            old_in_t = timezone.localtime(att.check_in).strftime('%I:%M %p') if att.check_in else '-'
            old_out_t = timezone.localtime(att.check_out).strftime('%I:%M %p') if att.check_out else '-'

            # Handle Manual Check-In Time entry by Admin
            if check_in_time_str is not None:
                time_clean = str(check_in_time_str).strip()
                if time_clean == '':
                    att.check_in = None
                else:
                    try:
                        if 'AM' in time_clean.upper() or 'PM' in time_clean.upper():
                            t_obj = datetime.datetime.strptime(time_clean, '%I:%M %p').time()
                        elif len(time_clean.split(':')) == 3:
                            t_obj = datetime.datetime.strptime(time_clean, '%H:%M:%S').time()
                        else:
                            t_obj = datetime.datetime.strptime(time_clean, '%H:%M').time()
                        
                        combined_in = datetime.datetime.combine(att.date, t_obj)
                        att.check_in = timezone.make_aware(combined_in, timezone.get_current_timezone())
                    except Exception as ex:
                        pass

            # Handle Manual Check-Out Time entry by Admin
            if check_out_time_str is not None:
                time_clean = str(check_out_time_str).strip()
                if time_clean == '':
                    att.check_out = None
                else:
                    try:
                        if 'AM' in time_clean.upper() or 'PM' in time_clean.upper():
                            t_obj = datetime.datetime.strptime(time_clean, '%I:%M %p').time()
                        elif len(time_clean.split(':')) == 3:
                            t_obj = datetime.datetime.strptime(time_clean, '%H:%M:%S').time()
                        else:
                            t_obj = datetime.datetime.strptime(time_clean, '%H:%M').time()
                        
                        combined_out = datetime.datetime.combine(att.date, t_obj)
                        att.check_out = timezone.make_aware(combined_out, timezone.get_current_timezone())
                    except Exception as ex:
                        pass

            if status and status != 'auto':
                att.status = status
                # If marked Present/Late/Half Day directly without times, fill standard shift times dynamically from user role policy
                shift_in = att.user.shift_start_time or datetime.time(9, 0)
                shift_out = att.user.shift_end_time or datetime.time(17, 0)
                
                in_mins = shift_in.hour * 60 + shift_in.minute
                out_mins = shift_out.hour * 60 + shift_out.minute
                if out_mins <= in_mins:
                    out_mins += 24 * 60
                
                if status == 'present' and not att.check_in:
                    combined_in = datetime.datetime.combine(att.date, shift_in)
                    att.check_in = timezone.make_aware(combined_in, timezone.get_current_timezone())
                    combined_out = datetime.datetime.combine(att.date, shift_out)
                    att.check_out = timezone.make_aware(combined_out, timezone.get_current_timezone())
                elif status == 'half_day' and not att.check_in:
                    combined_in = datetime.datetime.combine(att.date, shift_in)
                    att.check_in = timezone.make_aware(combined_in, timezone.get_current_timezone())
                    half_out_mins = in_mins + ((out_mins - in_mins) // 2)
                    half_out_time = datetime.time((half_out_mins // 60) % 24, half_out_mins % 60)
                    combined_out = datetime.datetime.combine(att.date, half_out_time)
                    att.check_out = timezone.make_aware(combined_out, timezone.get_current_timezone())
                elif status == 'absent':
                    att.check_in = None
                    att.check_out = None
            else:
                att.recalculate_status()

            att.updated_by = request.user
            if notes:
                att.notes = notes
            att.save()
            ensure_monthly_payrolls(att.date.month, att.date.year, request.user, force_recalculate=True)

            new_in_t = timezone.localtime(att.check_in).time() if att.check_in else None
            new_out_t = timezone.localtime(att.check_out).time() if att.check_out else None

            # Create Audit Log record with changed time info
            AttendanceAuditLog.objects.create(
                attendance=att,
                edited_by=request.user,
                old_status=old_status,
                new_status=att.status,
                old_check_in_time=old_in_t_obj,
                new_check_in_time=new_in_t,
                old_check_out_time=old_out_t_obj,
                new_check_out_time=new_out_t,
                notes=notes or att.notes or f'Manual Time Entry (In: {old_in_t} -> {timezone.localtime(att.check_in).strftime("%I:%M %p") if att.check_in else "-"}, Out: {old_out_t} -> {timezone.localtime(att.check_out).strftime("%I:%M %p") if att.check_out else "-"})'
            )
            return JsonResponse({
                'success': True, 
                'message': f'Attendance updated successfully! Status evaluated to: {att.get_status_display()}'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
            
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})

@login_required
def my_summary_view(request):
    auto_update_past_attendance_statuses()
    today = timezone.localdate()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    
    # Auto-ensure monthly payroll is calculated so user can see personal payslips summary
    ensure_monthly_payrolls(month, year, request.user, force_recalculate=True)

    # Calculate days in month
    days_in_month = calendar.monthrange(year, month)[1]
    day_numbers = list(range(1, days_in_month + 1))
    
    # Fetch all records for the logged-in user in this month
    records = Attendance.objects.filter(
        user=request.user,
        date__year=year,
        date__month=month
    ).order_by('date')
    
    records_by_day = {r.date.day: r for r in records}
    
    # Compile stats
    present_cnt = records.filter(Q(status='present') | Q(status='checked_in')).count()
    late_cnt = records.filter(status='late').count()
    half_day_cnt = records.filter(status='half_day').count()
    leave_cnt = 0
    
    total_days_passed = today.day if (today.month == month and today.year == year) else days_in_month
    recorded_days = records.count()
    
    absent_cnt = total_days_passed - recorded_days
    if absent_cnt < 0:
        absent_cnt = 0
        
    # Build day list
    day_list = []
    for d in day_numbers:
        d_date = datetime.date(year, month, d)
        rec = records_by_day.get(d, None)
        status = rec.status if rec else ''
        
        if not rec:
            if d_date > today:
                status = 'future'
            else:
                status = 'absent'
                    
        day_list.append({
            'day': d,
            'date': d_date,
            'record': rec,
            'status': status
        })
        
    # Personal payslips
    payslips = MonthlyPayroll.objects.filter(user=request.user).order_by('-year', '-month')[:12]
    sal_config = SalaryConfig.objects.filter(user=request.user).first()
    
    context = {
        'day_list': day_list,
        'present_cnt': present_cnt,
        'late_cnt': late_cnt,
        'half_day_cnt': half_day_cnt,
        'leave_cnt': leave_cnt,
        'absent_cnt': absent_cnt,
        'payslips': payslips,
        'sal_config': sal_config,
        'selected_month': month,
        'selected_year': year,
        'months': range(1, 13),
        'years': range(today.year - 2, today.year + 2),
    }
    return render(request, 'attendance/my_summary.html', context)

@login_required
def management_overview_view(request):
    auto_update_past_attendance_statuses()
    if not is_manager_or_owner(request.user):
        messages.error(request, 'Unauthorized access to Management Overview.')
        return redirect('attendance:dashboard')
        
    today = timezone.localdate()
    
    # 1. Date Filter
    date_str = request.GET.get('date', '').strip()
    selected_date = today
    if date_str:
        try:
            import datetime as dt_mod
            selected_date = dt_mod.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = today

    # 2. Branch Filter
    selected_branch_id = request.GET.get('branch', '').strip()
    branches = request.user.get_accessible_branches()
    
    if selected_branch_id:
        # Find users who checked in at this specific branch on selected_date
        checked_in_user_ids = Attendance.objects.filter(
            date=selected_date,
            branch_id=selected_branch_id,
            check_in__isnull=False
        ).values_list('user_id', flat=True)
        
        # Primary Main Branch filter: Include staff whose active_branch matches, or who checked in here
        branch_users = User.objects.filter(
            Q(active_branch_id=selected_branch_id) |
            Q(active_branch__isnull=True, branches__id=selected_branch_id) |
            Q(id__in=checked_in_user_ids)
        ).distinct()
    else:
        if is_owner(request.user) or request.user.has_all_branches:
            branch_users = User.objects.all()
        else:
            branch_users = User.objects.filter(
                Q(branches__in=branches) | Q(active_branch__in=branches)
            ).distinct()
            
    branch_users = branch_users.select_related('active_branch').prefetch_related('branches').order_by('employee_id', 'username')
    total_staff_count = branch_users.count()
    
    # 3. Selected Date's checkins
    date_records = Attendance.objects.filter(date=selected_date)
    if selected_branch_id:
        date_records = date_records.filter(
            Q(branch__id=selected_branch_id) | Q(user__branches__id=selected_branch_id)
        ).distinct()
    elif not (is_owner(request.user) or request.user.has_all_branches):
        date_records = date_records.filter(
            Q(branch__in=branches) | Q(user__branches__in=branches) | Q(user__active_branch__in=branches)
        ).distinct()
        
    stats = date_records.aggregate(
        checked_in_cnt=Count('id', filter=Q(check_in__isnull=False)),
        late_cnt=Count('id', filter=Q(status='late')),
        half_day_cnt=Count('id', filter=Q(status='half_day')),
        leave_cnt=Count('id', filter=Q(status='on_leave'))
    )
    checked_in_count = stats['checked_in_cnt'] or 0
    late_count = stats['late_cnt'] or 0
    half_day_count = stats['half_day_cnt'] or 0
    leave_count = stats['leave_cnt'] or 0
    absent_count = total_staff_count - (checked_in_count + leave_count)
    if absent_count < 0:
        absent_count = 0
        
    # Pending approvals - ONLY FOR ADMIN (OWNER)
    pending_leaves = LeaveRequest.objects.none()
    if is_owner(request.user):
        pending_permissions = PermissionRequest.objects.filter(status='pending').select_related('user')
        if selected_branch_id:
            pending_permissions = pending_permissions.filter(
                Q(user__branches__id=selected_branch_id) | Q(user__active_branch__id=selected_branch_id)
            ).distinct()
    else:
        pending_permissions = PermissionRequest.objects.none()

    # 4. Status Filter & Search Query
    status_filter = request.GET.get('status', '').strip()
    q_search = request.GET.get('q', '').strip()
        
    # Build dictionary map of date's attendance in 1 single query
    date_records_map = {rec.user_id: rec for rec in date_records.select_related('user', 'branch')}
    
    # Bulk query past unworked days in this month up to selected_date
    month_start = selected_date.replace(day=1)
    month_atts = Attendance.objects.filter(
        user__in=branch_users,
        date__gte=month_start,
        date__lte=selected_date
    )
    month_atts_map = {}
    for att in month_atts:
        month_atts_map.setdefault(att.user_id, {})[att.date] = att

    month_leaves = LeaveRequest.objects.none()
    month_leaves_map = {}
    for l in month_leaves:
        month_leaves_map.setdefault(l.user_id, []).append((l.start_date, l.end_date))

    staff_today_status = []
    for staff in branch_users:
        rec = date_records_map.get(staff.id)
        if rec:
            st = rec.status
        else:
            staff_lvs = month_leaves_map.get(staff.id, [])
            on_leave_today = any(sdate <= selected_date <= edate for sdate, edate in staff_lvs)
            if on_leave_today:
                st = 'on_leave'
            elif selected_date > today:
                st = 'future'
            else:
                allowed_offs = staff.monthly_off_count or 4
                u_atts = month_atts_map.get(staff.id, {})
                unworked_cnt = 0
                cur_d = month_start
                while cur_d <= selected_date:
                    d_att = u_atts.get(cur_d)
                    if not d_att:
                        is_lv = any(sdate <= cur_d <= edate for sdate, edate in staff_lvs)
                        if not is_lv:
                            unworked_cnt += 1
                    elif d_att.status == 'week_off':
                        unworked_cnt += 1
                    cur_d += datetime.timedelta(days=1)
                
                if unworked_cnt <= allowed_offs:
                    st = 'week_off'
                else:
                    st = 'absent'

        # Apply Status Filter
        if status_filter:
            if status_filter == 'checked_in' and not (rec and rec.check_in):
                continue
            elif status_filter == 'late' and st != 'late':
                continue
            elif status_filter == 'half_day' and st != 'half_day':
                continue
            elif status_filter == 'on_leave' and st != 'on_leave':
                continue
            elif status_filter == 'week_off' and st != 'week_off':
                continue
            elif status_filter == 'absent' and st != 'absent':
                continue

        # Apply Search Filter
        if q_search:
            q_lower = q_search.lower()
            name_match = (
                q_lower in staff.username.lower() or
                q_lower in (staff.first_name or '').lower() or
                q_lower in (staff.last_name or '').lower() or
                q_lower in (staff.employee_id or '').lower()
            )
            if not name_match:
                continue

        staff_today_status.append({
            'user': staff,
            'record': rec,
            'status': st
        })
    
    # Sort staff_today_status in ascending order based on employee_id
    staff_today_status.sort(key=lambda x: (x['user'].employee_id or '', x['user'].username or ''))

    # 5. CSV Export Handler
    if request.GET.get('export') == 'csv':
        import csv
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="management_overview_{selected_date.strftime("%Y%m%d")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Employee ID', 'Employee Name', 'Username', 'Role', 'Branch', 'Date', 'Status', 'Check-In Time', 'Mid-Day Check', 'Check-Out Time', 'Notes'])
        
        for item in staff_today_status:
            user = item['user']
            rec = item['record']
            status_display = item['status'].replace('_', ' ').title()
            
            full_name = f"{user.first_name} {user.last_name}".strip() or user.username
            branch_name = rec.branch.name if (rec and rec.branch) else (user.active_branch.name if user.active_branch else "All Branches")
            
            check_in_time = timezone.localtime(rec.check_in).strftime('%I:%M %p') if (rec and rec.check_in) else "-"
            mid_day_time = timezone.localtime(rec.mid_day_time).strftime('%I:%M %p') if (rec and rec.mid_day_time) else "-"
            check_out_time = timezone.localtime(rec.check_out).strftime('%I:%M %p') if (rec and rec.check_out) else "-"
            notes = rec.notes if (rec and rec.notes) else "-"
            
            writer.writerow([
                user.employee_id or '-',
                full_name,
                user.username,
                user.get_role_display() if hasattr(user, 'get_role_display') else getattr(user, 'role', '-'),
                branch_name,
                selected_date.strftime('%Y-%m-%d'),
                status_display,
                check_in_time,
                mid_day_time,
                check_out_time,
                notes
            ])
        return response
        
    context = {
        'today': today,
        'selected_date': selected_date,
        'selected_date_str': selected_date.strftime('%Y-%m-%d'),
        'branches': branches,
        'selected_branch_id': selected_branch_id,
        'status_filter': status_filter,
        'q_search': q_search,
        'total_staff_count': total_staff_count,
        'checked_in_count': checked_in_count,
        'late_count': late_count,
        'half_day_count': half_day_count,
        'leave_count': leave_count,
        'absent_count': absent_count,
        'pending_leaves_count': pending_leaves.count(),
        'pending_permissions_count': pending_permissions.count(),
        'pending_leaves': pending_leaves,
        'pending_permissions': pending_permissions,
        'staff_today_status': staff_today_status,
        'recent_audit_logs': AttendanceAuditLog.objects.select_related(
            'attendance', 'attendance__user', 'attendance__branch', 'edited_by'
        ).filter(attendance__date=selected_date).order_by('-timestamp'),
        'is_owner': is_owner(request.user),
    }
    return render(request, 'attendance/management_overview.html', context)


@login_required
def update_bank_details_ajax(request, user_id):
    if not is_owner(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user = get_object_or_404(User, id=user_id)
            acc_no = data.get('account_number')
            if acc_no is not None:
                acc_no = acc_no.strip()
                if acc_no and not acc_no.isdigit():
                    return JsonResponse({'success': False, 'message': 'Account number can accept only numbers (no letters or special characters).'})
                user.account_number = acc_no

            ifsc = data.get('ifsc_code')
            if ifsc is not None:
                ifsc = ifsc.strip().upper()
                if ifsc and not ifsc.isalnum():
                    return JsonResponse({'success': False, 'message': 'IFSC code can accept only numbers and capital letters.'})
                if ifsc and len(ifsc) != 11:
                    return JsonResponse({'success': False, 'message': 'IFSC code must be exactly 11 characters long (e.g., SBIN0001234).'})
                user.ifsc_code = ifsc

            user.designation = data.get('designation', user.designation)
            user.bank_name = data.get('bank_name', user.bank_name)
            doj_str = data.get('date_of_joining')
            if doj_str:
                try:
                    user.date_of_joining = datetime.datetime.strptime(doj_str, '%Y-%m-%d').date()
                except Exception:
                    pass
            user.save(update_fields=['designation', 'bank_name', 'account_number', 'ifsc_code', 'date_of_joining'])
            return JsonResponse({'success': True, 'message': 'Bank & Employee details updated successfully!'})
        except Exception as ex:
            return JsonResponse({'success': False, 'message': str(ex)})
    return JsonResponse({'success': False, 'message': 'Invalid request'})
