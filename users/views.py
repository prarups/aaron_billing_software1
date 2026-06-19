from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import models
from django.db.models import Sum, Count, F, Q, DecimalField, ExpressionWrapper
from django.views.generic import TemplateView
from django.contrib import messages
from billing.models import Bill
from core.models import Branch, Product, ProductRegistry
from .forms import BranchForm, StaffForm
from .models import User
from django.http import JsonResponse, HttpResponse
import json
import csv
from django.urls import reverse
@login_required
def dashboard_redirect(request):
    """Redirect user to the appropriate dashboard based on role."""
    if request.user.role == 'owner':
        return redirect('owner_dashboard')
    elif request.user.role == 'manager':
        return redirect('manager_dashboard')
    elif request.user.role == 'assistant_manager':
        return redirect('manager_dashboard')
    else:
        return redirect('staff_dashboard')

@login_required
def switch_branch(request):
    """Allows Managers/Owners to switch their active session branch."""
    if request.method == 'POST':
        branch_id = request.POST.get('branch_id')
        if branch_id:
            branch = get_object_or_404(Branch, id=branch_id)
            # Permission check - must be an authorized branch
            if branch in request.user.get_accessible_branches():
                request.user.active_branch = branch
                request.user.save()
    
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

class OwnerDashboardView(TemplateView):
    template_name = 'dashboards/owner.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_owner():
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        
        # Get from/to dates from request parameters
        from_date_str = self.request.GET.get('from_date')
        to_date_str = self.request.GET.get('to_date')
        
        is_filtered = False
        if from_date_str and to_date_str:
            try:
                start_date = timezone.datetime.strptime(from_date_str, '%Y-%m-%d').date()
                end_date = timezone.datetime.strptime(to_date_str, '%Y-%m-%d').date()
                is_filtered = True
            except ValueError:
                start_date = today
                end_date = today
        else:
            start_date = today
            end_date = today
            
        context['start_date'] = start_date.strftime('%Y-%m-%d') if start_date else ''
        context['end_date'] = end_date.strftime('%Y-%m-%d') if end_date else ''
        context['is_filtered'] = is_filtered

        # Overall Stats (either today, or for the specified date range)
        import datetime
        if is_filtered:
            start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
            end_datetime = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
            range_bills = Bill.objects.filter(created_at__range=(start_datetime, end_datetime))
            context['total_sales_today'] = range_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['transaction_count_today'] = range_bills.count()
            context['stats_label'] = f"Sales ({start_date.strftime('%d %b')} - {end_date.strftime('%d %b')})"
            context['trans_label'] = "Transactions (Period)"
        else:
            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
            today_bills = Bill.objects.filter(created_at__range=(today_start, today_end))
            context['total_sales_today'] = today_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['transaction_count_today'] = today_bills.count()
            context['stats_label'] = "Total Sales (Today)"
            context['trans_label'] = "Transactions"
            
        context['branch_count'] = Branch.objects.count()
        context['total_product_count'] = Product.objects.count()
        
        # Low Stock Alerts
        context['low_stock_count'] = ProductRegistry.objects.filter(stock_quantity__lte=F('low_stock_threshold')).count()
        
        # Branch performance - optimized with Subqueries to avoid cartesian join duplication
        from django.db.models import OuterRef, Subquery
        from django.db.models.functions import Coalesce
        
        # Subquery for active staff count
        staff_subquery = User.objects.filter(
            branches=OuterRef('pk'),
            role__in=['manager', 'staff']
        ).order_by().values('branches').annotate(cnt=Count('id')).values('cnt')

        # Subquery for sales (today or period range)
        import datetime
        if is_filtered:
            start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
            end_datetime = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
            sales_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(start_datetime, end_datetime)
            ).order_by().values('branch').annotate(total=Sum('total_amount')).values('total')
        else:
            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
            sales_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(today_start, today_end)
            ).order_by().values('branch').annotate(total=Sum('total_amount')).values('total')

        branches = Branch.objects.annotate(
            today_sales=Coalesce(
                Subquery(sales_subquery),
                0,
                output_field=models.DecimalField()
            ),
            active_staff_count=Coalesce(
                Subquery(staff_subquery),
                0,
                output_field=models.IntegerField()
            )
        ).order_by('-today_sales', 'name')
        context['branches'] = branches
        context['branches_by_code'] = branches.order_by('code', 'id')
        context['recent_bills'] = Bill.objects.order_by('-created_at')[:5]
        
        # Staff list (admins, managers, and staff) with pagination for scalability
        staff_qs = User.objects.filter(role__in=['owner', 'manager', 'assistant_manager', 'sales_staff']).prefetch_related('branches').order_by('employee_id', 'username')
        from django.core.paginator import Paginator
        paginator = Paginator(staff_qs, 25)  # 25 staff per page
        page_number = self.request.GET.get('staff_page', 1)
        context['staff_list'] = paginator.get_page(page_number)
        
        # Manager employee performance data
        managers = User.objects.filter(role__in=['manager', 'assistant_manager']).prefetch_related('branches')
        manager_data = []
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        for mgr in managers:
            staff_qs = User.objects.filter(role='sales_staff', branches__in=mgr.branches.all()).distinct()
            staff_info = []
            for staff in staff_qs:
                daily_sales = Bill.objects.filter(staff=staff, created_at__range=(today_start, today_end)).aggregate(total=Sum('total_amount'))['total'] or 0
                staff_info.append({
                    'employee_id': staff.employee_id,
                    'date_of_joining': staff.date_of_joining,
                    'sales': daily_sales,
                })
            manager_data.append({
                'manager': mgr,
                'staff': staff_info,
            })
        context['manager_performance'] = manager_data

        # Forms for creating new entries
        context['branch_form'] = BranchForm()
        context['staff_form'] = StaffForm()

        return context

class AssistantManagerDashboardView(TemplateView):
    template_name = 'dashboards/assistant_manager.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        branch = user.active_branch
        today = timezone.now().date()
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        if branch:
            branch_bills = Bill.objects.filter(branch=branch, created_at__range=(today_start, today_end))
            context['branch_sales_today'] = branch_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['product_count'] = Product.objects.count()
            context['staff_count'] = branch.assigned_users.filter(role='sales_staff').count()
            context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        return context
class ManagerDashboardView(TemplateView):
    template_name = 'dashboards/manager.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        branch = user.active_branch
        today = timezone.now().date()
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        # Branch-specific stats (same as AssistantManagerDashboardView)
        if branch:
            branch_bills = Bill.objects.filter(branch=branch, created_at__range=(today_start, today_end))
            context['branch_sales_today'] = branch_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['product_count'] = Product.objects.count()
            context['staff_count'] = branch.assigned_users.filter(role='sales_staff').count()
            context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        # Staff performance for manager/assistant manager
        if user.role in ['manager', 'assistant_manager']:
            staff_qs = User.objects.filter(role='sales_staff', branches__in=user.branches.all()).distinct()
            staff_info = []
            for staff in staff_qs:
                daily_sales = Bill.objects.filter(staff=staff, created_at__range=(today_start, today_end)).aggregate(total=Sum('total_amount'))['total'] or 0
                staff_info.append({
                    'employee_id': staff.employee_id,
                    'name': staff.get_full_name() or staff.username,
                    'date_of_joining': staff.date_of_joining,
                    'sales': daily_sales,
                })
            context['my_staff_performance'] = staff_info
        return context


class ManagerStaffPerformanceView(TemplateView):
    template_name = 'dashboards/manager_performance.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        # Get date range from query params, default to today
        from_date_str = self.request.GET.get('from')
        to_date_str = self.request.GET.get('to')
        try:
            from datetime import datetime
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else timezone.now().date()
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else timezone.now().date()
        except Exception:
            from_date = to_date = timezone.now().date()
        # Ensure proper ordering
        if from_date > to_date:
            from_date, to_date = to_date, from_date
        # Gather staff performance within range
        import datetime
        from_datetime = timezone.make_aware(datetime.datetime.combine(from_date, datetime.time.min))
        to_datetime = timezone.make_aware(datetime.datetime.combine(to_date, datetime.time.max))
        staff_qs = User.objects.filter(role__in=['sales_staff','manager'], branches__in=user.branches.all()).distinct()
        staff_info = []
        for staff in staff_qs:
            sales = Bill.objects.filter(staff=staff, created_at__range=(from_datetime, to_datetime)).aggregate(total=Sum('total_amount'))['total'] or 0
            staff_info.append({
                'employee_id': staff.employee_id,
                'name': staff.get_full_name() or staff.username,
                'date_of_joining': staff.date_of_joining,
                'sales': sales,
            })
        context['my_staff_performance'] = staff_info
        context['from_date'] = from_date.strftime('%Y-%m-%d')
        context['to_date'] = to_date.strftime('%Y-%m-%d')
        # Summary sales figures
        today = timezone.now().date()
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        today_sales = Bill.objects.filter(created_at__range=(today_start, today_end)).aggregate(total=Sum('total_amount'))['total'] or 0
        total_sales = Bill.objects.aggregate(total=Sum('total_amount'))['total'] or 0
        context['today_sales'] = today_sales
        context['total_sales'] = total_sales
        return context

    def render_to_response(self, context, **response_kwargs):
        # CSV export handling
        if self.request.GET.get('format') == 'csv':
            import csv
            from datetime import datetime
            from django.http import HttpResponse
            from django.db.models.functions import TruncDate
            # Determine date range
            from_date_str = context.get('from_date')
            to_date_str = context.get('to_date')
            try:
                start_date = datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else timezone.now().date()
                end_date = datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else timezone.now().date()
            except Exception:
                start_date = end_date = timezone.now().date()
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            # Query bills for selected staff within the date range, aggregated per staff per day
            import datetime
            start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
            end_datetime = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
            staff_qs = User.objects.filter(role__in=['sales_staff','manager'], branches__in=self.request.user.branches.all()).distinct()
            sales_qs = Bill.objects.filter(
                staff__in=staff_qs,
                created_at__range=(start_datetime, end_datetime)
            ).annotate(date=TruncDate('created_at')).values(
                'staff__employee_id', 'staff__username', 'date'
            ).annotate(daily_sales=Sum('total_amount')).order_by('staff__employee_id', 'date')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="staff_performance_detail.csv"'
            writer = csv.writer(response)
            writer.writerow(['Emp. ID', 'Name', 'Date', 'Sales'])
            for row in sales_qs:
                writer.writerow([
                    row['staff__employee_id'],
                    row['staff__username'],
                    row['date'].strftime('%Y-%m-%d') if row['date'] else '',
                    row['daily_sales'] or 0,
                ])
            return response
        return super().render_to_response(context, **response_kwargs)

# Export CSV for backward compatibility (optional helper view)
def export_manager_performance_csv(request):
    view = ManagerStaffPerformanceView()
    # Reuse the same logic by delegating to the view's render_to_response
    return view.as_view()(request)







    # Reuse the same context as ManagerDashboardView (branch-specific stats)
    def get_context_data(self, **kwargs):
        # Duplicate logic from ManagerDashboardView, adjusting if needed
        context = super().get_context_data(**kwargs)
        branch = self.request.user.active_branch
        if not branch:
            return context
        today = timezone.now().date()
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        branch_bills = Bill.objects.filter(branch=branch, created_at__range=(today_start, today_end))
        context['branch_sales_today'] = branch_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['product_count'] = Product.objects.count()
        context['staff_count'] = branch.assigned_users.filter(role='sales_staff').count()
        context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        return context

    # Duplicate get_context_data removed

class StaffDashboardView(TemplateView):
    template_name = 'dashboards/staff.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        branch = self.request.user.active_branch
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        staff_bills = Bill.objects.filter(staff=self.request.user, branch=branch, created_at__range=(today_start, today_end))
        
        context['my_sales_today'] = staff_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['my_bill_count'] = staff_bills.count()
        context['recent_my_bills'] = staff_bills.order_by('-created_at')[:5]
        context['today_date'] = today.isoformat()
        return context


# --- BRANCH CRUD VIEWS ---

@login_required
def branch_create(request):
    if not request.user.is_owner():
        return redirect('dashboard')
    if request.method == 'POST':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save()
            messages.success(request, f"Branch '{branch.name}' created successfully.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                return JsonResponse({'success': True})
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                errors = {field: [err['message'] for err in errs] for field, errs in form.errors.get_json_data().items()}
                return JsonResponse({'success': False, 'errors': errors})
            errors_str = " ".join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            messages.error(request, f"Failed to create branch. {errors_str}")
    return redirect(reverse('owner_dashboard') + '#branches')

@login_required
def branch_edit(request, pk):
    if not request.user.is_owner():
        return redirect('dashboard')
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, f"Branch '{branch.name}' updated successfully.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                return JsonResponse({'success': True})
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                errors = {field: [err['message'] for err in errs] for field, errs in form.errors.get_json_data().items()}
                return JsonResponse({'success': False, 'errors': errors})
            errors_str = " ".join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            messages.error(request, f"Failed to update branch. {errors_str}")
    return redirect(reverse('owner_dashboard') + '#branches')

@login_required
def branch_delete(request, pk):
    if not request.user.is_owner():
        return redirect('dashboard')
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == 'POST':
        name = branch.name
        branch.delete()
        messages.success(request, f"Branch '{name}' deleted successfully.")
    return redirect(reverse('owner_dashboard') + '#branches')


# --- STAFF CRUD VIEWS ---

@login_required
def staff_create(request):
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
        return redirect('dashboard')
    if request.method == 'POST':
        form = StaffForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Staff account '{user.username}' created successfully.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                return JsonResponse({'success': True})
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                errors = {field: [err['message'] for err in errs] for field, errs in form.errors.get_json_data().items()}
                return JsonResponse({'success': False, 'errors': errors})
            errors_str = " ".join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            print('Staff Create Form Errors:', form.errors)
            messages.error(request, f"Failed to create staff. {errors_str}")
    return redirect(reverse('owner_dashboard') + '#staff')

@login_required
def staff_edit(request, pk):
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
        return redirect('dashboard')
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = StaffForm(request.POST, instance=user)
        if form.is_valid():
            saved_user = form.save()
            if saved_user == request.user:
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, saved_user)
            messages.success(request, f"Staff account '{user.username}' updated successfully.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                return JsonResponse({'success': True})
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == 'true':
                errors = {field: [err['message'] for err in errs] for field, errs in form.errors.get_json_data().items()}
                return JsonResponse({'success': False, 'errors': errors})
            errors_str = " ".join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            print('Staff Edit Form Errors:', form.errors)
            messages.error(request, f"Failed to update staff. {errors_str}")
    return redirect(reverse('owner_dashboard') + '#staff')

@login_required
def staff_delete(request, pk):
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
        return redirect('dashboard')
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f"Staff account '{username}' deleted successfully.")
    return redirect(reverse('owner_dashboard') + '#staff')

# --- TOGGLE STAFF ACTIVE STATUS ---
@login_required
def toggle_staff_active(request, staff_id):
    """AJAX endpoint to toggle a staff member's active status.
    Expects a POST request with a JSON payload containing `is_active` boolean.
    Only owners can perform this action.
    """
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    staff = get_object_or_404(User, pk=staff_id)
    if staff == request.user:
        return JsonResponse({'error': 'You cannot deactivate your own account.'}, status=400)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            is_active = data.get('is_active')
            if isinstance(is_active, bool):
                staff.is_active = is_active
                staff.save()
                return JsonResponse({'status': 'success', 'is_active': staff.is_active})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request.'}, status=400)


@login_required
def toggle_product_rights(request, staff_id):
    """AJAX endpoint to toggle a manager's product edit rights.
    Expects a POST request with a JSON payload containing `has_product_rights` boolean.
    Only owners can perform this action.
    """
    if not request.user.is_owner():
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    staff = get_object_or_404(User, pk=staff_id)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            has_product_rights = data.get('has_product_rights')
            if isinstance(has_product_rights, bool):
                staff.has_product_rights = has_product_rights
                staff.save()
                return JsonResponse({'status': 'success', 'has_product_rights': staff.has_product_rights})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request.'}, status=400)


@login_required
def toggle_bill_edit_rights(request, staff_id):
    """AJAX endpoint to toggle a staff member's bill edit rights.
    Expects a POST request with a JSON payload containing `has_bill_edit_rights` boolean.
    Only owners can perform this action.
    """
    if not request.user.is_owner():
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    staff = get_object_or_404(User, pk=staff_id)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            has_bill_edit_rights = data.get('has_bill_edit_rights')
            if isinstance(has_bill_edit_rights, bool):
                staff.has_bill_edit_rights = has_bill_edit_rights
                staff.save()
                return JsonResponse({'status': 'success', 'has_bill_edit_rights': staff.has_bill_edit_rights})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request.'}, status=400)


@login_required
def export_dashboard_sales_csv(request):
    """Exports date-wise and branch-wise total sales amount for the specified date range.
    Only owners and managers are authorized.
    """
    if request.user.role == 'sales_staff':
        from django.http import HttpResponse
        return HttpResponse("Unauthorized", status=403)
        
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')
    
    today = timezone.now().date()
    try:
        start_date = timezone.datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else today
        end_date = timezone.datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else today
    except ValueError:
        start_date = today
        end_date = today
        
    import csv
    from django.http import HttpResponse
    from django.db.models.functions import TruncDate
    
    filename = f"branch_sales_report_{start_date}_to_{end_date}.csv"
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Branch Code', 'Branch Name', 'Location', 'Total Sales (INR)'])
    
    # Query date-wise and branch-wise total sales
    import datetime
    start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
    end_datetime = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
    sales_data = Bill.objects.filter(
        created_at__range=(start_datetime, end_datetime)
    ).annotate(
        date=TruncDate('created_at')
    ).values(
        'date', 'branch__id', 'branch__name', 'branch__code', 'branch__location'
    ).annotate(
        total_sales=Sum('total_amount')
    ).order_by('date', 'branch__name')
    
    for row in sales_data:
        writer.writerow([
            row['date'].strftime('%Y-%m-%d') if row['date'] else '',
            row['branch__code'] or '',
            row['branch__name'] or '',
            row['branch__location'] or '',
            int(row['total_sales']) if row['total_sales'] is not None else 0
        ])
        
    return response


@login_required
def export_branches_csv(request):
    if not request.user.is_owner():
        return HttpResponse("Unauthorized", status=403)
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="branches_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Branch ID / Code', 'Branch Name', 'Location', 'Contact Number', 'Invoice Prefix', 'Sales Staff Count'])
    
    from core.models import Branch
    from django.db.models import Count
    
    branches = Branch.objects.annotate(
        active_staff_count=Count('assigned_users', filter=models.Q(assigned_users__role='sales_staff'))
    ).order_by('code', 'id')
    
    for b in branches:
        writer.writerow([
            b.code or b.id,
            b.name,
            b.location,
            b.contact_number or '-',
            b.invoice_prefix,
            f"{b.active_staff_count} staff"
        ])
        
    return response


@login_required
def export_staff_csv(request):
    if not request.user.is_owner():
        return HttpResponse("Unauthorized", status=403)
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales_staff_accounts.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Employee ID', 'Username', 'First Name', 'Last Name', 'Email', 
        'Role', 'Status', 'Product Rights', 'Bill Edit Rights', 
        'Date of Joining', 'Mobile Number', 'Address', 'Assigned Branches'
    ])
    
    staff_qs = User.objects.filter(
        role__in=['owner', 'manager', 'assistant_manager', 'sales_staff']
    ).prefetch_related('branches').order_by('employee_id', 'username')
    
    for s in staff_qs:
        branches_str = ", ".join([b.name for b in s.branches.all()])
        status = "Active" if s.is_active else "Inactive"
        prod_rights = "Yes" if s.has_product_rights else "No"
        bill_rights = "Yes" if s.has_bill_edit_rights else "No"
        
        writer.writerow([
            s.employee_id or '-',
            s.username,
            s.first_name,
            s.last_name,
            s.email or '-',
            s.get_role_display(),
            status,
            prod_rights,
            bill_rights,
            s.date_of_joining.strftime('%Y-%m-%d') if s.date_of_joining else '-',
            s.mobile_number or '-',
            s.address or '-',
            branches_str or '-'
        ])
        
    return response

