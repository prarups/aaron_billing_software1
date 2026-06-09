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
from django.http import JsonResponse
import json
from django.urls import reverse
@login_required
def dashboard_redirect(request):
    if request.user.role == 'owner':
        return redirect('owner_dashboard')
    elif request.user.role == 'manager':
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
            # Permission check
            if request.user.is_owner() or request.user.branches.filter(id=branch.id).exists():
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
        if is_filtered:
            range_bills = Bill.objects.filter(created_at__date__range=[start_date, end_date])
            context['total_sales_today'] = range_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            context['transaction_count_today'] = range_bills.count()
            context['stats_label'] = f"Sales ({start_date.strftime('%d %b')} - {end_date.strftime('%d %b')})"
            context['trans_label'] = "Transactions (Period)"
        else:
            today_bills = Bill.objects.filter(created_at__date=today)
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
        if is_filtered:
            sales_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__date__range=[start_date, end_date]
            ).order_by().values('branch').annotate(total=Sum('total_amount')).values('total')
        else:
            sales_subquery = Bill.objects.filter(
                branch=OuterRef('pk'),
                created_at__date=today
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
        context['recent_bills'] = Bill.objects.order_by('-created_at')[:5]
        
        # Staff list (admins, managers, and staff) with pagination for scalability
        staff_qs = User.objects.filter(role__in=['owner', 'manager', 'staff']).prefetch_related('branches').order_by('username')
        from django.core.paginator import Paginator
        paginator = Paginator(staff_qs, 25)  # 25 staff per page
        page_number = self.request.GET.get('staff_page', 1)
        context['staff_list'] = paginator.get_page(page_number)
        
        # Forms for creating new entries
        context['branch_form'] = BranchForm()
        context['staff_form'] = StaffForm()
        
        return context

class ManagerDashboardView(TemplateView):
    template_name = 'dashboards/manager.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = self.request.user.active_branch
        if not branch:
            return context
            
        today = timezone.now().date()
        branch_bills = Bill.objects.filter(branch=branch, created_at__date=today)
        
        context['branch_sales_today'] = branch_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['product_count'] = Product.objects.count()
        context['staff_count'] = branch.assigned_users.filter(role='staff').count()
        
        context['recent_branch_bills'] = Bill.objects.filter(branch=branch).order_by('-created_at')[:5]
        return context

class StaffDashboardView(TemplateView):
    template_name = 'dashboards/staff.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        branch = self.request.user.active_branch
        staff_bills = Bill.objects.filter(staff=self.request.user, branch=branch, created_at__date=today)
        
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
    if not request.user.is_owner():
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
    return redirect(reverse('owner_dashboard') + '#staff')

@login_required
def staff_edit(request, pk):
    if not request.user.is_owner():
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
    return redirect(reverse('owner_dashboard') + '#staff')

@login_required
def staff_delete(request, pk):
    if not request.user.is_owner():
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
    if not request.user.is_owner():
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
def export_dashboard_sales_csv(request):
    """Exports date-wise and branch-wise total sales amount for the specified date range.
    Only owners and managers are authorized.
    """
    if request.user.role == 'staff':
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
    sales_data = Bill.objects.filter(
        created_at__date__range=[start_date, end_date]
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

