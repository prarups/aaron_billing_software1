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
        
        # Overall Stats
        today_bills = Bill.objects.filter(created_at__date=today)
        context['total_sales_today'] = today_bills.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        context['transaction_count_today'] = today_bills.count()
        context['branch_count'] = Branch.objects.count()
        context['total_product_count'] = Product.objects.count()
        
        # Low Stock Alerts
        context['low_stock_count'] = ProductRegistry.objects.filter(stock_quantity__lte=F('low_stock_threshold')).count()
        
        # Branch performance
        branches = Branch.objects.annotate(
            today_sales=Sum('bills__total_amount', filter=models.Q(bills__created_at__date=today)),
            active_staff_count=Count('assigned_users', filter=models.Q(assigned_users__role__in=['manager', 'staff']))
        )
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
        else:
            messages.error(request, "Failed to create branch. Please check inputs.")
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
        else:
            messages.error(request, "Failed to update branch. Please check inputs.")
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
        else:
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
        else:
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

