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
from django.db.models import Count, Q
from django.conf import settings
from users.models import User
from core.models import Branch
from .models import Attendance, LeaveRequest, PermissionRequest, SalaryConfig, MonthlyPayroll
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
    return user.role == 'owner'

def is_manager_or_owner(user):
    return user.role in ['owner', 'regional_manager', 'manager', 'assistant_manager']

@login_required
def attendance_dashboard(request):
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
        branch_users = User.objects.filter(branches__in=branches).distinct().exclude(role='owner')
        if is_owner(request.user):
            branch_users = User.objects.all().exclude(role='owner')
            
        total_staff_count = branch_users.count()
        
        # Today's checkins
        today_records = Attendance.objects.filter(date=today)
        if not is_owner(request.user):
            today_records = today_records.filter(branch__in=branches)
            
        checked_in_count = today_records.filter(check_in__isnull=False).count()
        late_count = today_records.filter(status='late').count()
        half_day_count = today_records.filter(status='half_day').count()
        leave_count = today_records.filter(status='on_leave').count()
        absent_count = total_staff_count - (checked_in_count + leave_count)
        if absent_count < 0:
            absent_count = 0
            
        # Pending approvals
        pending_leaves = LeaveRequest.objects.filter(status='pending')
        pending_permissions = PermissionRequest.objects.filter(status='pending')
        if not is_owner(request.user):
            pending_leaves = pending_leaves.filter(user__branches__in=branches).distinct()
            pending_permissions = pending_permissions.filter(user__branches__in=branches).distinct()
            
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
        
        unrecorded_leaves = LeaveRequest.objects.filter(
            user=request.user,
            status='approved',
            start_date__gte=start_of_month,
            end_date__lte=today
        ).exclude(
            start_date__in=personal_month_atts.values_list('date', flat=True)
        ).count()
        
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
            status = 'present'
            
            # Combine today's date with the user's shift start time in local timezone
            shift_start = request.user.shift_start_time
            grace_mins = request.user.grace_period_minutes
            
            local_shift_datetime = timezone.make_aware(
                datetime.datetime.combine(today, shift_start),
                timezone.get_current_timezone()
            )
            
            # Calculate late threshold
            late_threshold = local_shift_datetime + datetime.timedelta(minutes=grace_mins)
            
            if now > late_threshold:
                status = 'late'
                
            # If there's an approved leave for today, set status to 'on_leave'
            on_leave = LeaveRequest.objects.filter(
                user=request.user, 
                start_date__lte=today, 
                end_date__gte=today, 
                status='approved'
            ).exists()
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
                
            attendance.check_out = timezone.now()
            attendance.check_out_photo = photo_file
            attendance.check_out_lat = lat
            attendance.check_out_lng = lng
            attendance.save()
            
            return JsonResponse({
                'success': True, 
                'message': 'Checked out successfully!', 
                'time': timezone.localtime(attendance.check_out).strftime('%I:%M %p')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


# --- Leave Views ---

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
        pending_perms = PermissionRequest.objects.filter(status='pending').exclude(user=user)
        past_perms_qs = PermissionRequest.objects.exclude(status='pending').exclude(user=user)
    elif is_manager_or_owner(user):
        pending_perms = PermissionRequest.objects.filter(
            user__branches__in=branches,
            status='pending'
        ).exclude(user=user).distinct()
        past_perms_qs = PermissionRequest.objects.filter(
            user__branches__in=branches
        ).exclude(status='pending').exclude(user=user).distinct()
    else:
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
    
    # Load dynamic limits
    try:
        salary_config = user.salary_config
        max_permissions = salary_config.max_permissions_per_month
        max_hours = salary_config.max_hours_per_permission
    except Exception:
        max_permissions = 2
        max_hours = Decimal('2.00')

    # Count how many permissions the user has requested/approved in the current month (excluding rejected)
    today_date = timezone.localdate()
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
        'max_permissions': max_permissions,
        'max_hours': max_hours,
        'permissions_used_this_month': permissions_used_this_month,
    }
    return render(request, 'attendance/permission_list.html', context)

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
            
            # 1. Calculate duration and validate hourly limit
            start_dt = datetime.datetime.combine(date_val, start_time)
            end_dt = datetime.datetime.combine(date_val, end_time)
            if end_dt <= start_dt:
                messages.error(request, 'Failed to submit request: End time must be after start time.')
                return redirect('attendance:permission_list')
                
            duration_hours = Decimal(str((end_dt - start_dt).total_seconds() / 3600.0))
            
            try:
                salary_config = request.user.salary_config
                max_hours = salary_config.max_hours_per_permission
                max_perms = salary_config.max_permissions_per_month
            except Exception:
                max_hours = Decimal('2.00')
                max_perms = 2
                
            if duration_hours > max_hours:
                messages.error(
                    request,
                    f'Failed to submit request: Duration ({duration_hours:.2f} hours) '
                    f'exceeds your permitted limit of {max_hours:.2f} hours per request.'
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
    if not is_manager_or_owner(request.user):
        messages.error(request, 'Unauthorized access.')
        return redirect('attendance:permission_list')
        
    perm = get_object_or_404(PermissionRequest, pk=pk)
    
    # Manager check
    if not is_owner(request.user):
        user_branches = request.user.get_accessible_branches()
        overlap = perm.user.branches.filter(id__in=user_branches.values_list('id', flat=True))
        if not overlap.exists():
            messages.error(request, 'You do not have permission to approve permissions for this staff.')
            return redirect('attendance:permission_list')
            
    try:
        if action == 'approve':
            perm.status = 'approved'
            perm.approved_by = request.user
            perm.save()
            messages.success(request, f'Permission for {perm.user.username} approved.')
        elif action == 'reject':
            perm.status = 'rejected'
            perm.approved_by = request.user
            perm.save()
            messages.success(request, f'Permission for {perm.user.username} rejected.')
    except Exception as e:
        messages.error(request, f'Error processing permission approval: {e}')
        
    return redirect('attendance:permission_list')


# --- Reports Views ---

@login_required
def attendance_reports(request):
    if not is_manager_or_owner(request.user):
        messages.error(request, 'Unauthorized access.')
        return redirect('attendance:dashboard')
        
    branches = request.user.get_accessible_branches()
    users = User.objects.filter(branches__in=branches).distinct()
    
    if is_owner(request.user):
        users = User.objects.all()
        
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
            
    records = Attendance.objects.filter(date__range=(start_date, end_date))
    
    if not is_owner(request.user):
        records = records.filter(branch__in=branches)
        
    if selected_branch:
        records = records.filter(branch_id=selected_branch)
    if selected_user:
        records = records.filter(user_id=selected_user)
        
    records = records.order_by('-date', 'user__username')
    
    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="attendance_report_{start_date}_{end_date}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date', 'Employee ID', 'Username', 'Branch', 'Check In', 'Check Out', 'Mid Day Check', 'Status', 'Notes'])
        
        for r in records:
            check_in_time = timezone.localtime(r.check_in).strftime('%Y-%m-%d %I:%M %p') if r.check_in else ''
            check_out_time = timezone.localtime(r.check_out).strftime('%Y-%m-%d %I:%M %p') if r.check_out else ''
            mid_day = timezone.localtime(r.mid_day_time).strftime('%Y-%m-%d %I:%M %p') if r.mid_day_time else ''
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
    grid_users = users.exclude(role='owner')
    if selected_branch:
        grid_users = grid_users.filter(branches__id=selected_branch).distinct()
    if selected_user:
        grid_users = grid_users.filter(id=selected_user)
        
    grid_data = []
    for u in grid_users:
        u_days = []
        p_cnt = 0
        l_cnt = 0
        a_cnt = 0
        lv_cnt = 0
        h_cnt = 0
        
        # Load all records for this user for this month
        month_atts = Attendance.objects.filter(
            user=u,
            date__year=grid_year,
            date__month=grid_month
        )
        atts_by_day = {a.date.day: a for a in month_atts}
        
        for d in day_numbers:
            d_date = datetime.date(grid_year, grid_month, d)
            status = ''
            rec_id = None
            
            if d in atts_by_day:
                att = atts_by_day[d]
                status = att.status
                rec_id = att.id
                if status == 'present': p_cnt += 1
                elif status == 'late': l_cnt += 1
                elif status == 'half_day': h_cnt += 1
                elif status == 'on_leave': lv_cnt += 1
                elif status == 'absent': a_cnt += 1
            else:
                if d_date > today:
                    status = 'future'
                else:
                    # Check approved leaves
                    leave = LeaveRequest.objects.filter(
                        user=u,
                        start_date__lte=d_date,
                        end_date__gte=d_date,
                        status='approved'
                    ).first()
                    if leave:
                        status = 'on_leave'
                        lv_cnt += 1
                    else:
                        status = 'absent'
                        a_cnt += 1
            
            u_days.append({
                'day': d,
                'status': status,
                'record_id': rec_id
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
            }
        })
        
    context = {
        'page_obj': page_obj,  # paginated page object
        'branches': branches,
        'users': users,
        'selected_branch': selected_branch,
        'selected_user': selected_user,
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
    }
    return render(request, 'attendance/reports.html', context)


# --- Salary/Payroll Views ---

@login_required
def salary_list(request):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized access to salary configs.')
        return redirect('attendance:dashboard')
        
    users = User.objects.all().order_by('username')
    
    # Make sure SalaryConfig exists for all users
    for user in users:
        SalaryConfig.objects.get_or_create(user=user)
        
    # Processed Payroll list
    today = timezone.localdate()
    selected_month = int(request.GET.get('month', today.month))
    selected_year = int(request.GET.get('year', today.year))
    
    payrolls = MonthlyPayroll.objects.filter(month=selected_month, year=selected_year)
    
    # Base Salary Config filtering logic
    q_staff = request.GET.get('q_staff', '').strip()
    branch_staff = request.GET.get('branch_staff', '').strip()
    active_tab = request.GET.get('tab', 'process')
    
    if q_staff:
        users = users.filter(Q(username__icontains=q_staff) | Q(employee_id__icontains=q_staff))
        
    if branch_staff:
        users = users.filter(branches__id=branch_staff)
        
    users = users.distinct()
    
    # Fetch all branches for the filter dropdown
    branches = Branch.objects.all().order_by('name')
    
    context = {
        'users': users,
        'payrolls': payrolls,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': range(1, 13),
        'years': range(today.year - 2, today.year + 2),
        'branches': branches,
        'q_staff': q_staff,
        'selected_branch_id': branch_staff,
        'active_tab': active_tab,
    }
    return render(request, 'attendance/payroll.html', context)

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
            late = request.POST.get('late_deduction_amount', '0')
            lop = request.POST.get('lop_deduction_amount', '0')
            max_perms = request.POST.get('max_permissions_per_month', '2')
            max_hours = request.POST.get('max_hours_per_permission', '2.00')
            
            config.monthly_base_salary = Decimal(base)
            config.late_deduction_amount = Decimal(late)
            config.lop_deduction_amount = Decimal(lop)
            config.max_permissions_per_month = int(max_perms)
            config.max_hours_per_permission = Decimal(max_hours)
            config.save()
            
            messages.success(request, f'Salary & Permission configuration updated for {user_obj.username}.')
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
        return JsonResponse({'success': False, 'message': 'Unauthorized'})
        
    if request.method == 'POST':
        try:
            month = int(request.POST.get('month'))
            year = int(request.POST.get('year'))
            
            # Find all users
            users = User.objects.exclude(role='owner')
            
            # Setup month date ranges
            first_day = datetime.date(year, month, 1)
            days_in_month = calendar.monthrange(year, month)[1]
            last_day = datetime.date(year, month, days_in_month)
            
            success_count = 0
            failed_users = []
            
            for user in users:
                try:
                    with transaction.atomic():
                        config, _ = SalaryConfig.objects.get_or_create(user=user)
                        
                        # Fetch attendance summary for this month
                        late_days = Attendance.objects.filter(
                            user=user, 
                            date__range=(first_day, last_day),
                            status='late'
                        ).count()
                        
                        present_att = Attendance.objects.filter(
                            user=user, 
                            date__range=(first_day, last_day)
                        )
                        
                        present_days = 0
                        absent_days = 0
                        approved_leaves = 0
                        unapproved_leaves = 0
                        
                        current_date = first_day
                        while current_date <= last_day:
                            att_rec = present_att.filter(date=current_date).first()
                            
                            if att_rec:
                                if att_rec.status in ['present', 'late']:
                                    present_days += 1
                                elif att_rec.status == 'half_day':
                                    present_days += 0.5
                                    absent_days += 0.5
                                elif att_rec.status == 'on_leave':
                                    leave = LeaveRequest.objects.filter(
                                        user=user, 
                                        start_date__lte=current_date, 
                                        end_date__gte=current_date, 
                                        status='approved'
                                    ).first()
                                    if leave:
                                        approved_leaves += 1
                                    else:
                                        unapproved_leaves += 1
                            else:
                                leave = LeaveRequest.objects.filter(
                                    user=user, 
                                    start_date__lte=current_date, 
                                    end_date__gte=current_date, 
                                    status='approved'
                                ).first()
                                if leave:
                                    approved_leaves += 1
                                else:
                                    absent_days += 1
                                    unapproved_leaves += 1
                                    
                            current_date += datetime.timedelta(days=1)
                        
                        lop_days_to_deduct = max(0, unapproved_leaves - 4)
                        
                        late_deduction = late_days * config.late_deduction_amount
                        lop_deduction = lop_days_to_deduct * config.lop_deduction_amount
                        total_deductions = late_deduction + lop_deduction
                        
                        net_salary = config.monthly_base_salary - total_deductions
                        if net_salary < 0:
                            net_salary = 0
                            
                        MonthlyPayroll.objects.update_or_create(
                            user=user,
                            month=month,
                            year=year,
                            defaults={
                                'present_days': int(present_days),
                                'absent_days': int(absent_days),
                                'late_days': late_days,
                                'approved_leaves': approved_leaves,
                                'unapproved_leaves': unapproved_leaves,
                                'base_salary': config.monthly_base_salary,
                                'deductions': total_deductions,
                                'net_salary': net_salary,
                                'processed_by': request.user,
                                'status': 'draft'
                            }
                        )
                        success_count += 1
                except Exception as user_err:
                    failed_users.append(f"{user.username} ({user_err})")
            
            if failed_users:
                messages.warning(request, f"Payroll generated for {success_count} employees. Failed for: {', '.join(failed_users)}")
            else:
                messages.success(request, f"Payroll generated successfully for all {success_count} staff members.")
                
            return redirect(f"{reverse('attendance:payroll_list')}?month={month}&year={year}")
        except Exception as e:
            messages.error(request, f"Error generating payroll: {e}")
            return redirect('attendance:payroll_list')
        except Exception as e:
            messages.error(request, f"Error generating payroll: {e}")
            return redirect('attendance:payroll_list')
            
    return redirect('attendance:payroll_list')

@login_required
def mark_payroll_paid(request, payroll_id):
    if not is_owner(request.user):
        messages.error(request, 'Unauthorized.')
        return redirect('attendance:dashboard')
        
    payroll = get_object_or_404(MonthlyPayroll, pk=payroll_id)
    payroll.status = 'paid'
    payroll.save()
    messages.success(request, f"Salary of Rs.{payroll.net_salary} for {payroll.user.username} marked as PAID.")
    return redirect(f"{reverse('attendance:payroll_list')}?month={payroll.month}&year={payroll.year}")

@login_required
def edit_attendance_ajax(request, pk):
    if not is_manager_or_owner(request.user):
        return JsonResponse({'success': False, 'message': 'Unauthorized access.'})
        
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            status = data.get('status')
            notes = data.get('notes')
            
            att = get_object_or_404(Attendance, pk=pk)
            
            # Manager check
            if not is_owner(request.user):
                user_branches = request.user.get_accessible_branches()
                if att.branch not in user_branches:
                    return JsonResponse({'success': False, 'message': 'Unauthorized for this branch.'})
                    
            att.status = status
            att.notes = notes
            att.save()
            return JsonResponse({'success': True, 'message': 'Attendance updated successfully!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
            
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})

@login_required
def my_summary_view(request):
    today = timezone.localdate()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    
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
    present_cnt = records.filter(status='present').count()
    late_cnt = records.filter(status='late').count()
    half_day_cnt = records.filter(status='half_day').count()
    leave_cnt = records.filter(status='on_leave').count()
    
    total_days_passed = today.day if (today.month == month and today.year == year) else days_in_month
    recorded_days = records.count()
    
    unrecorded_leaves = LeaveRequest.objects.filter(
        user=request.user,
        status='approved',
        start_date__gte=datetime.date(year, month, 1),
        end_date__lte=datetime.date(year, month, days_in_month)
    ).exclude(
        start_date__in=records.values_list('date', flat=True)
    ).count()
    
    absent_cnt = total_days_passed - recorded_days - unrecorded_leaves
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
                leave = LeaveRequest.objects.filter(
                    user=request.user,
                    start_date__lte=d_date,
                    end_date__gte=d_date,
                    status='approved'
                ).first()
                if leave:
                    status = 'on_leave'
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
    if not is_manager_or_owner(request.user):
        messages.error(request, 'Unauthorized access to Management Overview.')
        return redirect('attendance:dashboard')
        
    today = timezone.localdate()
    branches = request.user.get_accessible_branches()
    branch_users = User.objects.filter(branches__in=branches).distinct().exclude(role='owner')
    if is_owner(request.user):
        branch_users = User.objects.all().exclude(role='owner')
        
    total_staff_count = branch_users.count()
    
    # Today's checkins
    today_records = Attendance.objects.filter(date=today)
    if not is_owner(request.user):
        today_records = today_records.filter(branch__in=branches)
        
    checked_in_count = today_records.filter(check_in__isnull=False).count()
    late_count = today_records.filter(status='late').count()
    half_day_count = today_records.filter(status='half_day').count()
    leave_count = today_records.filter(status='on_leave').count()
    absent_count = total_staff_count - (checked_in_count + leave_count)
    if absent_count < 0:
        absent_count = 0
        
    # Pending approvals
    pending_leaves = LeaveRequest.objects.filter(status='pending')
    pending_permissions = PermissionRequest.objects.filter(status='pending')
    if not is_owner(request.user):
        pending_leaves = pending_leaves.filter(user__branches__in=branches).distinct()
        pending_permissions = pending_permissions.filter(user__branches__in=branches).distinct()
        
    # Also fetch all staff checking-in details today for overview log
    staff_today_status = []
    for staff in branch_users:
        rec = today_records.filter(user=staff).first()
        status = rec.status if rec else 'absent'
        staff_today_status.append({
            'user': staff,
            'record': rec,
            'status': status
        })
        
    context = {
        'today': today,
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
    }
    return render(request, 'attendance/management_overview.html', context)
