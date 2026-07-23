from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import models
from django.db.models import Sum, Count, F, Q, DecimalField, ExpressionWrapper
from django.views.generic import TemplateView
from django.contrib import messages
from billing.models import Bill, BranchGoal, BillItem
from core.models import Branch, Product, ProductRegistry
from .forms import BranchForm, StaffForm
from .models import User, CustomRole
from django.http import JsonResponse, HttpResponse
import json
import csv
from django.urls import reverse
from django import forms


class RoleForm(forms.ModelForm):
    class Meta:
        model = CustomRole
        fields = ['name', 'has_pos_access', 'has_attendance_access', 'has_all_branches_access', 'has_product_rights', 'has_bill_edit_rights']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'has_pos_access': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_attendance_access': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_all_branches_access': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_product_rights': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_bill_edit_rights': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }



def add_branch_goal_context(user, context):
    branch = user.active_branch
    if branch:
        today = timezone.now().date()
        today = timezone.now().date()
        current_month_start = today.replace(day=1)
        import datetime
        import calendar
        current_month_start_dt = timezone.make_aware(datetime.datetime(today.year, today.month, 1, 0, 0, 0))
        _, last_day = calendar.monthrange(today.year, today.month)
        current_month_end_dt = timezone.make_aware(datetime.datetime(today.year, today.month, last_day, 23, 59, 59))
        
        goal = BranchGoal.objects.filter(branch=branch, month=current_month_start).first()
        monthly_sales = Bill.objects.filter(branch=branch, created_at__range=(current_month_start_dt, current_month_end_dt)).aggregate(total=Sum('total_amount'))['total'] or 0
        
        context['branch_goal_target'] = int(goal.target_sales) if goal else 0
        context['branch_goal_sales'] = int(monthly_sales)
        if context['branch_goal_target'] > 0:
            context['branch_goal_percent'] = min(100, int((context['branch_goal_sales'] * 100) / context['branch_goal_target']))
            context['branch_goal_percent_exact'] = round((context['branch_goal_sales'] * 100) / context['branch_goal_target'], 1)
        else:
            context['branch_goal_percent'] = 0
            context['branch_goal_percent_exact'] = 0
    else:
        context['branch_goal_target'] = 0
        context['branch_goal_sales'] = 0
        context['branch_goal_percent'] = 0
        context['branch_goal_percent_exact'] = 0


@login_required
def dashboard_redirect(request):
    """Redirect user to the appropriate dashboard based on role."""
    if request.user.role in ['owner', 'regional_manager']:
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

@login_required
def role_create(request):
    """Handle creation of a CustomRole.
    POST saves and redirects back to the management page.
    """
    if not request.user.is_owner():
        messages.error(request, "Only admins can create roles.")
        return redirect('branch_staff_management')

    if request.method == "POST":
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save()
            messages.success(request, f"✅ Custom role '{role.name}' created successfully!")
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, f"{field}: {err}")
    return redirect('branch_staff_management')

class OwnerDashboardView(TemplateView):
    template_name = 'dashboards/owner.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_owner() or request.user.role == 'regional_manager'):
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

        # Overall Stats (optimized to fetch all sums in a single query)
        import datetime
        from billing.return_models import ReturnRequest
        if is_filtered:
            start_datetime = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
            end_datetime = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
            range_bills = Bill.objects.filter(created_at__range=(start_datetime, end_datetime))
            
            aggs = range_bills.aggregate(
                sales=Sum('total_amount'),
                cash=Sum('cash_amount'),
                online=Sum('online_amount')
            )
            # Add return exchange payments collected in same period
            ret_aggs = ReturnRequest.objects.filter(
                invoice__in=range_bills,
                status=ReturnRequest.Status.APPROVED
            ).aggregate(ret_cash=Sum('cash_amount'), ret_online=Sum('online_amount'))
            context['total_sales_today'] = (aggs['sales'] or 0) + (ret_aggs['ret_cash'] or 0) + (ret_aggs['ret_online'] or 0)
            context['total_cash_today'] = (aggs['cash'] or 0) + (ret_aggs['ret_cash'] or 0)
            context['total_online_today'] = (aggs['online'] or 0) + (ret_aggs['ret_online'] or 0)
            context['transaction_count_today'] = range_bills.count()
            context['stats_label'] = f"Sales ({start_date.strftime('%d %b')} - {end_date.strftime('%d %b')})"
            context['trans_label'] = "Transactions (Period)"
        else:
            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
            today_bills = Bill.objects.filter(created_at__range=(today_start, today_end))
            
            aggs = today_bills.aggregate(
                sales=Sum('total_amount'),
                cash=Sum('cash_amount'),
                online=Sum('online_amount')
            )
            # Add return exchange payments collected today
            ret_aggs = ReturnRequest.objects.filter(
                invoice__in=today_bills,
                status=ReturnRequest.Status.APPROVED
            ).aggregate(ret_cash=Sum('cash_amount'), ret_online=Sum('online_amount'))
            context['total_sales_today'] = (aggs['sales'] or 0) + (ret_aggs['ret_cash'] or 0) + (ret_aggs['ret_online'] or 0)
            context['total_cash_today'] = (aggs['cash'] or 0) + (ret_aggs['ret_cash'] or 0)
            context['total_online_today'] = (aggs['online'] or 0) + (ret_aggs['ret_online'] or 0)
            context['transaction_count_today'] = today_bills.count()
            context['stats_label'] = "Total Sales (Today)"
            context['trans_label'] = "Transactions"
            
        context['branch_count'] = Branch.objects.count()
        context['total_product_count'] = Product.objects.count()
        
        # Low Stock Alerts
        context['low_stock_count'] = ProductRegistry.objects.filter(stock_quantity__lte=F('low_stock_threshold')).count()
        
        # Stock Summary stats
        total_current_stock = ProductRegistry.objects.aggregate(Sum('stock_quantity'))['stock_quantity__sum'] or 0
        if is_filtered:
            total_items_sold = BillItem.objects.filter(
                bill__created_at__range=(start_datetime, end_datetime)
            ).aggregate(Sum('quantity'))['quantity__sum'] or 0
        else:
            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
            total_items_sold = BillItem.objects.filter(
                bill__created_at__range=(today_start, today_end)
            ).aggregate(Sum('quantity'))['quantity__sum'] or 0
            
        context['total_current_stock'] = total_current_stock
        context['total_items_sold'] = total_items_sold
        
        # Branch performance - optimized with Subqueries to avoid cartesian join duplication
        from django.db.models import OuterRef, Subquery
        from django.db.models.functions import Coalesce
        
        # Subquery for active staff count
        staff_subquery = User.objects.filter(
            branches=OuterRef('pk'),
            role__in=['sales_staff', 'assistant_manager']
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
            
            cash_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(start_datetime, end_datetime)
            ).order_by().values('branch').annotate(total=Sum('cash_amount')).values('total')
            
            online_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(start_datetime, end_datetime)
            ).order_by().values('branch').annotate(total=Sum('online_amount')).values('total')
        else:
            today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
            today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
            sales_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(today_start, today_end)
            ).order_by().values('branch').annotate(total=Sum('total_amount')).values('total')
            
            cash_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(today_start, today_end)
            ).order_by().values('branch').annotate(total=Sum('cash_amount')).values('total')
            
            online_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__range=(today_start, today_end)
            ).order_by().values('branch').annotate(total=Sum('online_amount')).values('total')

        branches = Branch.objects.annotate(
            today_sales=Coalesce(
                Subquery(sales_subquery),
                0,
                output_field=models.DecimalField()
            ),
            today_cash=Coalesce(
                Subquery(cash_subquery),
                0,
                output_field=models.DecimalField()
            ),
            today_online=Coalesce(
                Subquery(online_subquery),
                0,
                output_field=models.DecimalField()
            ),
            active_staff_count=Coalesce(
                Subquery(staff_subquery),
                0,
                output_field=models.IntegerField()
            )
        ).order_by('-today_sales', 'name')
        
        # Attach current month goal and actual monthly sales
        today = timezone.now().date()
        current_month_start = today.replace(day=1)
        import datetime
        import calendar
        current_month_start_dt = timezone.make_aware(datetime.datetime(today.year, today.month, 1, 0, 0, 0))
        _, last_day = calendar.monthrange(today.year, today.month)
        current_month_end_dt = timezone.make_aware(datetime.datetime(today.year, today.month, last_day, 23, 59, 59))

        goals_dict = {g.branch_id: g.target_sales for g in BranchGoal.objects.filter(month=current_month_start)}
        monthly_sales_dict = {
            row['branch']: row['total']
            for row in Bill.objects.filter(created_at__range=(current_month_start_dt, current_month_end_dt))
            .values('branch')
            .annotate(total=Sum('total_amount'))
        }

        branches_list = list(branches)
        for b in branches_list:
            b.current_goal = int(goals_dict.get(b.id, 0))
            b.current_month_sales = int(monthly_sales_dict.get(b.id, 0))
            if b.current_goal > 0:
                b.current_goal_percent = min(100, int((b.current_month_sales * 100) / b.current_goal))
                b.current_goal_percent_exact = round((b.current_month_sales * 100) / b.current_goal, 1)
            else:
                b.current_goal_percent = 0
                b.current_goal_percent_exact = 0
        context['branches'] = branches_list
        
        # Filter and sort branches_by_code in memory to avoid running the heavy Subquery annotations query twice
        branch_search = self.request.GET.get('branch_search', '').strip()
        if branch_search:
            search_lower = branch_search.lower()
            branches_by_code_list = [
                b for b in branches_list
                if search_lower in b.name.lower() or 
                   (b.location and search_lower in b.location.lower()) or 
                   (b.invoice_prefix and search_lower in b.invoice_prefix.lower()) or 
                   (b.code and str(b.code) == branch_search)
            ]
        else:
            branches_by_code_list = list(branches_list)
            
        # Sort in memory by code, fallback to ID
        branches_by_code_list.sort(key=lambda b: (b.code or 0, b.id))
        
        for b in branches_by_code_list:
            b.current_goal = int(goals_dict.get(b.id, 0))
            b.current_month_sales = int(monthly_sales_dict.get(b.id, 0))
            if b.current_goal > 0:
                b.current_goal_percent = min(100, int((b.current_month_sales * 100) / b.current_goal))
                b.current_goal_percent_exact = round((b.current_month_sales * 100) / b.current_goal, 1)
            else:
                b.current_goal_percent = 0
                b.current_goal_percent_exact = 0
        context['branches_by_code'] = branches_by_code_list
        context['branch_search'] = branch_search
        
        context['recent_bills'] = Bill.objects.order_by('-created_at')[:5]
        
        # Staff list (admins, managers, and staff) without pagination for client-side search scalability
        staff_qs = User.objects.filter(role__in=['owner', 'manager', 'assistant_manager', 'sales_staff']).prefetch_related('branches').order_by('employee_id', 'username')
        context['staff_list'] = staff_qs
        
        # Manager employee performance data
        managers = User.objects.filter(role__in=['manager', 'assistant_manager']).prefetch_related('branches')
        manager_data = []
        import datetime
        today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
        # Pre-calculate sales for all staff for today to avoid N+1 queries
        sales_data = Bill.objects.filter(created_at__range=(today_start, today_end)).values('staff').annotate(total=Sum('total_amount'))
        staff_sales_dict = {item['staff']: item['total'] or 0 for item in sales_data}

        # Prefetch sales_staff to avoid N+1 database hits in managers loop
        managed_branch_ids = set()
        for mgr in managers:
            for b in mgr.branches.all():
                managed_branch_ids.add(b.id)
                
        all_sales_staff = User.objects.filter(
            role='sales_staff',
            branches__in=managed_branch_ids
        ).prefetch_related('branches').distinct()
        
        # Map branch_id -> list of staff
        branch_staff_map = {}
        for staff in all_sales_staff:
            for b in staff.branches.all():
                branch_staff_map.setdefault(b.id, []).append(staff)

        for mgr in managers:
            staff_seen = set()
            staff_info = []
            for b in mgr.branches.all():
                for staff in branch_staff_map.get(b.id, []):
                    if staff.id not in staff_seen:
                        staff_seen.add(staff.id)
                        daily_sales = staff_sales_dict.get(staff.id, 0)
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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

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
            aggs = branch_bills.aggregate(
                sales=Sum('total_amount'),
                cash=Sum('cash_amount'),
                online=Sum('online_amount')
            )
            context['branch_sales_today'] = aggs['sales'] or 0
            context['branch_cash_today'] = aggs['cash'] or 0
            context['branch_online_today'] = aggs['online'] or 0
            context['product_count'] = Product.objects.count()
            context['staff_count'] = branch.assigned_users.filter(role__in=['sales_staff', 'assistant_manager']).exclude(id=user.id).count()
            context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        add_branch_goal_context(user, context)
        return context

class ManagerDashboardView(TemplateView):
    template_name = 'dashboards/manager.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

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
            aggs = branch_bills.aggregate(
                sales=Sum('total_amount'),
                cash=Sum('cash_amount'),
                online=Sum('online_amount')
            )
            context['branch_sales_today'] = aggs['sales'] or 0
            context['branch_cash_today'] = aggs['cash'] or 0
            context['branch_online_today'] = aggs['online'] or 0
            context['product_count'] = Product.objects.count()
            context['staff_count'] = branch.assigned_users.filter(role__in=['sales_staff', 'assistant_manager']).exclude(id=user.id).count()
            context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        add_branch_goal_context(user, context)
        # Staff performance for manager/assistant manager
        if user.role in ['manager', 'assistant_manager']:
            staff_qs = User.objects.filter(role__in=['sales_staff', 'assistant_manager'], branches__in=user.branches.all()).exclude(id=user.id).distinct()
            
            # Pre-calculate sales for all staff for today to avoid N+1 queries
            sales_data = Bill.objects.filter(staff__in=staff_qs, created_at__range=(today_start, today_end)).values('staff').annotate(total=Sum('total_amount'))
            staff_sales_dict = {item['staff']: item['total'] or 0 for item in sales_data}

            staff_info = []
            for staff in staff_qs:
                daily_sales = staff_sales_dict.get(staff.id, 0)
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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

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
        staff_qs = User.objects.filter(role__in=['sales_staff', 'manager', 'assistant_manager'], branches__in=user.branches.all()).distinct()
        
        # Pre-calculate sales for all staff for date range to avoid N+1 queries
        sales_data = Bill.objects.filter(staff__in=staff_qs, created_at__range=(from_datetime, to_datetime)).values('staff').annotate(total=Sum('total_amount'))
        staff_sales_dict = {item['staff']: item['total'] or 0 for item in sales_data}

        staff_info = []
        for staff in staff_qs:
            sales = staff_sales_dict.get(staff.id, 0)
            staff_info.append({
                'employee_id': staff.employee_id,
                'name': staff.get_full_name() or staff.username,
                'designation': staff.get_role_display(),
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
            staff_qs = User.objects.filter(role__in=['sales_staff', 'manager', 'assistant_manager'], branches__in=self.request.user.branches.all()).distinct()
            sales_qs = Bill.objects.filter(
                staff__in=staff_qs,
                created_at__range=(start_datetime, end_datetime)
            ).annotate(date=TruncDate('created_at')).values(
                'staff__employee_id', 'staff__username', 'staff__role', 'date'
            ).annotate(daily_sales=Sum('total_amount')).order_by('staff__employee_id', 'date')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="staff_performance_detail.csv"'
            writer = csv.writer(response)
            writer.writerow(['Emp. ID', 'Name', 'Designation', 'Date', 'Sales'])
            role_display_map = {
                'owner': 'Admin',
                'manager': 'Manager',
                'assistant_manager': 'Assistant Manager',
                'sales_staff': 'Sales Staff'
            }
            for row in sales_qs:
                writer.writerow([
                    row['staff__employee_id'],
                    row['staff__username'],
                    role_display_map.get(row['staff__role'], row['staff__role']),
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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

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
        add_branch_goal_context(self.request.user, context)
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
    return redirect(reverse('branch_staff_management') + '?tab=branches')

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
    return redirect(reverse('branch_staff_management') + '?tab=branches')

@login_required
def branch_delete(request, pk):
    messages.error(request, "Branch deletion is disabled to protect historical sales data. Please archive or rename instead.")
    return redirect(reverse('branch_staff_management') + '?tab=branches')


@login_required
def set_branch_goal_ajax(request):
    if not request.user.is_owner():
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if request.method == 'POST':
        branch_id = request.POST.get('branch_id')
        month_str = request.POST.get('month') # expected "YYYY-MM"
        target_sales = request.POST.get('target_sales')
        
        if not branch_id or not month_str or not target_sales:
            return JsonResponse({'success': False, 'error': 'Missing required fields.'}, status=400)
            
        try:
            branch = get_object_or_404(Branch, pk=branch_id)
            # Parse YYYY-MM
            month_date = timezone.datetime.strptime(month_str, '%Y-%m').date()
            # Normalize to first day of the month
            month_date = month_date.replace(day=1)
            target_sales_val = int(float(target_sales))
            
            goal, created = BranchGoal.objects.update_or_create(
                branch=branch,
                month=month_date,
                defaults={'target_sales': target_sales_val}
            )
            return JsonResponse({
                'success': True,
                'branch_id': branch.id,
                'month': month_str,
                'target_sales': int(goal.target_sales)
            })
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid format or values.'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'POST method required.'}, status=405)


@login_required
def get_suggested_goal_ajax(request):
    if not request.user.is_owner():
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
    branch_id = request.GET.get('branch_id')
    month_str = request.GET.get('month') # expected "YYYY-MM"
    
    if not branch_id or not month_str:
        return JsonResponse({'success': False, 'error': 'Missing required parameters.'}, status=400)
        
    try:
        branch = get_object_or_404(Branch, pk=branch_id)
        month_date = timezone.datetime.strptime(month_str, '%Y-%m').date()
        month_date = month_date.replace(day=1)
        
        # Calculate previous month
        if month_date.month == 1:
            prev_year = month_date.year - 1
            prev_month = 12
        else:
            prev_year = month_date.year
            prev_month = month_date.month - 1
            
        import datetime
        import calendar
        import math
        
        prev_start = timezone.make_aware(datetime.datetime(prev_year, prev_month, 1, 0, 0, 0))
        _, last_day = calendar.monthrange(prev_year, prev_month)
        prev_end = timezone.make_aware(datetime.datetime(prev_year, prev_month, last_day, 23, 59, 59))
        
        previous_sales = Bill.objects.filter(branch=branch, created_at__range=(prev_start, prev_end)).aggregate(total=Sum('total_amount'))['total'] or 0
        
        suggested = int(math.ceil((float(previous_sales) * 1.10) / 1000.0) * 1000)
        if suggested < 10000:
            suggested = 10000
            
        return JsonResponse({
            'success': True,
            'branch_id': branch.id,
            'month': month_str,
            'previous_sales': int(previous_sales),
            'suggested_sales': suggested
        })
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid format.'}, status=400)


# --- STAFF CRUD VIEWS ---

@login_required
def staff_create(request):
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager', 'regional_manager']):
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
            messages.error(request, f"Failed to create staff. {errors_str}")
    return redirect(reverse('branch_staff_management') + '?tab=staff')

@login_required
def staff_edit(request, pk):
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager', 'regional_manager']):
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
            messages.error(request, f"Failed to update staff. {errors_str}")
    return redirect(reverse('branch_staff_management') + '?tab=staff')

@login_required
def staff_delete(request, pk):
    messages.error(request, "Staff account deletion is disabled to protect transaction history. Please toggle their active status to Deactivate instead.")
    return redirect(reverse('branch_staff_management') + '?tab=staff')

# --- TOGGLE STAFF ACTIVE STATUS ---
@login_required
def toggle_staff_active(request, staff_id):
    """AJAX endpoint to toggle a staff member's active status.
    Expects a POST request with a JSON payload containing `is_active` boolean.
    Only owners can perform this action.
    """
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager', 'regional_manager']):
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
def toggle_pos_access(request, staff_id):
    """AJAX endpoint to toggle a staff member's POS portal access."""
    if not request.user.is_owner():
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    staff = get_object_or_404(User, pk=staff_id)
    if staff == request.user:
        return JsonResponse({'error': 'You cannot restrict your own portal access.'}, status=400)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            has_pos_access = data.get('has_pos_access')
            if isinstance(has_pos_access, bool):
                staff.has_pos_access = has_pos_access
                staff.save()
                return JsonResponse({'status': 'success', 'has_pos_access': staff.has_pos_access})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request.'}, status=400)


@login_required
def toggle_attendance_access(request, staff_id):
    """AJAX endpoint to toggle a staff member's Attendance portal access."""
    if not request.user.is_owner():
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    staff = get_object_or_404(User, pk=staff_id)
    if staff == request.user:
        return JsonResponse({'error': 'You cannot restrict your own portal access.'}, status=400)
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            has_attendance_access = data.get('has_attendance_access')
            if isinstance(has_attendance_access, bool):
                staff.has_attendance_access = has_attendance_access
                staff.save()
                return JsonResponse({'status': 'success', 'has_attendance_access': staff.has_attendance_access})
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
    writer.writerow(['Date', 'Branch Code', 'Branch Name', 'Location', 'Total Sales (INR)', 'Cash Sales (INR)', 'Online Sales (INR)'])
    
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
        total_sales=Sum('total_amount'),
        cash_sales=Sum('cash_amount'),
        online_sales=Sum('online_amount')
    ).order_by('date', 'branch__name')
    
    for row in sales_data:
        writer.writerow([
            row['date'].strftime('%Y-%m-%d') if row['date'] else '',
            row['branch__code'] or '',
            row['branch__name'] or '',
            row['branch__location'] or '',
            int(row['total_sales']) if row['total_sales'] is not None else 0,
            int(row['cash_sales']) if row['cash_sales'] is not None else 0,
            int(row['online_sales']) if row['online_sales'] is not None else 0
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
        active_staff_count=Count('assigned_users', filter=models.Q(assigned_users__role__in=['sales_staff', 'assistant_manager']))
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


@login_required
def get_staff_online_status(request):
    """API endpoint to get the online/offline status of all staff members."""
    if not (request.user.is_owner() or request.user.role in ['manager', 'assistant_manager']):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    staff_qs = User.objects.filter(
        role__in=['owner', 'manager', 'assistant_manager', 'sales_staff']
    ).only('id', 'last_activity')
    
    status_data = {}
    for staff in staff_qs:
        status_data[staff.id] = staff.is_online
        
    return JsonResponse(status_data)


@login_required
def portal_choice(request):
    """Render the portal selection screen."""
    return render(request, 'registration/portal_choice.html')


@login_required
def billing_redirect(request):
    """Redirect to the appropriate POS/Billing dashboard depending on role."""
    if request.user.role in ['owner', 'regional_manager']:
        return redirect('owner_dashboard')
    elif request.user.role in ['manager', 'assistant_manager']:
        return redirect('manager_dashboard')
    else:
        return redirect('staff_dashboard')


@login_required
def select_portal(request, portal_name):
    """Set the active portal in user session and redirect appropriately."""
    if portal_name == 'attendance':
        if not request.user.is_owner() and not request.user.has_attendance_access:
            from django.contrib import messages
            messages.error(request, "You do not have permission to access the HR & Attendance portal.")
            return redirect('portal_choice')
        request.session['active_portal'] = portal_name
        return redirect('attendance:dashboard')
    elif portal_name == 'billing':
        if not request.user.is_owner() and not request.user.has_pos_access:
            from django.contrib import messages
            messages.error(request, "You do not have permission to access the Billing & POS portal.")
            return redirect('portal_choice')
        request.session['active_portal'] = portal_name
        return redirect('billing_redirect')
    return redirect('portal_choice')


@login_required
def branch_staff_management(request):
    """Manage branches and sales staff."""
    if not (request.user.is_owner() or request.user.role == 'regional_manager'):
        return redirect('dashboard')
    
    active_tab = request.GET.get('tab', 'branches')
    if request.user.role == 'regional_manager':
        active_tab = 'staff'
        
    if active_tab not in ['branches', 'staff']:
        active_tab = 'branches'
    
    from django.db.models import Count, Sum, Q, F
    from django.db.models.functions import Coalesce
    from django.db.models import OuterRef, Subquery
    from core.models import Branch, Product, ProductRegistry
    from billing.models import Bill, BillItem
    from users.models import User
    import datetime
    
    today = timezone.now().date()
    
    # Subquery for active staff count
    staff_subquery = User.objects.filter(
        branches=OuterRef('pk'),
        role__in=['sales_staff', 'assistant_manager']
    ).order_by().values('branches').annotate(cnt=Count('id')).values('cnt')
    
    # Subquery for sales (today)
    today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    today_end = timezone.make_aware(datetime.datetime.combine(today, datetime.time.max))
    sales_subquery = Bill.objects.filter(
        branch=OuterRef('pk'),
        created_at__range=(today_start, today_end)
    ).order_by().values('branch').annotate(total=Sum('total_amount')).values('total')
    
    cash_subquery = Bill.objects.filter(
        branch=OuterRef('pk'),
        created_at__range=(today_start, today_end)
    ).order_by().values('branch').annotate(total=Sum('cash_amount')).values('total')
    
    online_subquery = Bill.objects.filter(
        branch=OuterRef('pk'),
        created_at__range=(today_start, today_end)
    ).order_by().values('branch').annotate(total=Sum('online_amount')).values('total')
    
    branches = Branch.objects.annotate(
        today_sales=Coalesce(Subquery(sales_subquery), 0, output_field=models.DecimalField()),
        today_cash=Coalesce(Subquery(cash_subquery), 0, output_field=models.DecimalField()),
        today_online=Coalesce(Subquery(online_subquery), 0, output_field=models.DecimalField()),
        active_staff_count=Coalesce(Subquery(staff_subquery), 0, output_field=models.IntegerField())
    ).order_by('-today_sales', 'name')
    
    current_month_start = today.replace(day=1)
    import calendar
    current_month_start_dt = timezone.make_aware(datetime.datetime(today.year, today.month, 1, 0, 0, 0))
    _, last_day = calendar.monthrange(today.year, today.month)
    current_month_end_dt = timezone.make_aware(datetime.datetime(today.year, today.month, last_day, 23, 59, 59))
    
    goals_dict = {g.branch_id: g.target_sales for g in BranchGoal.objects.filter(month=current_month_start)}
    monthly_sales_dict = {
        row['branch']: row['total']
        for row in Bill.objects.filter(created_at__range=(current_month_start_dt, current_month_end_dt))
        .values('branch')
        .annotate(total=Sum('total_amount'))
    }
    
    branches_list = list(branches)
    for b in branches_list:
        b.current_goal = int(goals_dict.get(b.id, 0))
        b.current_month_sales = int(monthly_sales_dict.get(b.id, 0))
        if b.current_goal > 0:
            b.current_goal_percent = min(100, int((b.current_month_sales * 100) / b.current_goal))
            b.current_goal_percent_exact = round((b.current_month_sales * 100) / b.current_goal, 1)
        else:
            b.current_goal_percent = 0
            b.current_goal_percent_exact = 0
            
    branch_search = request.GET.get('branch_search', '').strip()
    if branch_search:
        search_lower = branch_search.lower()
        branches_by_code_list = [
            b for b in branches_list
            if search_lower in b.name.lower() or 
               (b.location and search_lower in b.location.lower()) or 
               (b.invoice_prefix and search_lower in b.invoice_prefix.lower()) or 
               (b.code and str(b.code) == branch_search)
        ]
    else:
        branches_by_code_list = list(branches_list)
        
    branches_by_code_list.sort(key=lambda b: (b.code or 0, b.id))
    for b in branches_by_code_list:
        b.current_goal = int(goals_dict.get(b.id, 0))
        b.current_month_sales = int(monthly_sales_dict.get(b.id, 0))
        if b.current_goal > 0:
            b.current_goal_percent = min(100, int((b.current_month_sales * 100) / b.current_goal))
            b.current_goal_percent_exact = round((b.current_month_sales * 100) / b.current_goal, 1)
        else:
            b.current_goal_percent = 0
            b.current_goal_percent_exact = 0
            
    staff_qs = User.objects.all().prefetch_related('branches').order_by('employee_id', 'username')
    custom_roles = CustomRole.objects.all()
    
    from users.forms import BranchForm, StaffForm
    branch_form = BranchForm()
    staff_form = StaffForm()
    
    context = {
        'branches': branches_list,
        'branches_by_code': branches_by_code_list,
        'branch_search': branch_search,
        'staff_list': staff_qs,
        'custom_roles': custom_roles,
        'all_branches': Branch.objects.all(),
        'branch_form': branch_form,
        'staff_form': staff_form,
        'active_tab': active_tab,
    }
    return render(request, 'dashboards/management.html', context)


