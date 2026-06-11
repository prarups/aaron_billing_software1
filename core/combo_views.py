from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from decimal import Decimal
from core.models import Branch, Product, ProductRegistry, ComboGroup, ComboTier

def calculate_optimal_combo_price(item_prices, tiers_list):
    """
    item_prices: list of floats/Decimals representing base prices of items in the combo.
    tiers_list: list of tuples/dicts with quantity and price, e.g. [(2, 180), (5, 400)]
    Returns the minimum cost to buy all these items.
    """
    prices = sorted([float(p) for p in item_prices], reverse=True)
    n = len(prices)
    # Sort tiers by quantity descending
    sorted_tiers = sorted(tiers_list, key=lambda t: t[0], reverse=True)
    memo = {}

    def solve(index):
        if index >= n:
            return 0.0
        if index in memo:
            return memo[index]

        # Option 1: Buy current item as single
        best = prices[index] + solve(index + 1)

        # Option 2: Apply any of the available tiers
        for qty, tier_price in sorted_tiers:
            if qty <= n - index:
                cost = float(tier_price) + solve(index + qty)
                if cost < best:
                    best = cost

        memo[index] = best
        return best

    return solve(0)

@login_required
def combo_list(request):
    if request.user.role == 'staff':
        messages.error(request, "Access denied. Only Owners and Managers can manage combos.")
        return redirect('dashboard')
    
    combos = ComboGroup.objects.prefetch_related('branches', 'products', 'tiers').all().order_by('-created_at')
    return render(request, 'core/combo_list.html', {
        'combos': combos
    })

@login_required
@transaction.atomic
def combo_create(request):
    if request.user.role == 'staff':
        messages.error(request, "Access denied. Only Owners and Managers can manage combos.")
        return redirect('dashboard')
    
    branches = request.user.get_accessible_branches().order_by('name')
    products = Product.objects.all().order_by('name')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        selected_branch = request.POST.get('branches')  # single branch
        selected_products = request.POST.getlist('products')
        
        tier_quantities = request.POST.getlist('tier_quantity[]')
        tier_prices = request.POST.getlist('tier_price[]')
        
        if not name:
            messages.error(request, "Combo Name is required.")
        else:
            # Create ComboGroup
            combo = ComboGroup.objects.create(name=name, is_active=is_active)
            if selected_branch:
                combo.branches.set([selected_branch])
            if selected_products:
                combo.products.set(selected_products)
                
            # Create tiers
            for qty_str, price_str in zip(tier_quantities, tier_prices):
                if qty_str and price_str:
                    try:
                        qty = int(qty_str)
                        price = Decimal(price_str)
                        if qty > 0 and price >= 0:
                            ComboTier.objects.create(combo_group=combo, quantity=qty, price=price)
                    except (ValueError, TypeError):
                        pass
                        
            messages.success(request, f"Combo '{combo.name}' created successfully.")
            return redirect('combo_list')
            
    return render(request, 'core/combo_form.html', {
        'branches': branches,
        'products': products,
        'title': 'Create Combo Offer'
    })

@login_required
@transaction.atomic
def combo_edit(request, pk):
    if request.user.role == 'staff':
        messages.error(request, "Access denied. Only Owners and Managers can manage combos.")
        return redirect('dashboard')
    
    combo = get_object_or_404(ComboGroup, pk=pk)
    branches = request.user.get_accessible_branches().order_by('name')
    products = Product.objects.all().order_by('name')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        selected_branch = request.POST.get('branches')  # single branch
        selected_products = request.POST.getlist('products')
        
        tier_quantities = request.POST.getlist('tier_quantity[]')
        tier_prices = request.POST.getlist('tier_price[]')
        
        if not name:
            messages.error(request, "Combo Name is required.")
        else:
            combo.name = name
            combo.is_active = is_active
            combo.save()
            
            selected_branch = request.POST.get('branches')  # single branch
            if selected_branch:
                combo.branches.set([selected_branch])
            else:
                combo.branches.clear()
                
            if selected_products:
                combo.products.set(selected_products)
            else:
                combo.products.clear()
                
            # Clear old tiers and recreate
            combo.tiers.all().delete()
            for qty_str, price_str in zip(tier_quantities, tier_prices):
                if qty_str and price_str:
                    try:
                        qty = int(qty_str)
                        price = Decimal(price_str)
                        if qty > 0 and price >= 0:
                            ComboTier.objects.create(combo_group=combo, quantity=qty, price=price)
                    except (ValueError, TypeError):
                        pass
                        
            messages.success(request, f"Combo '{combo.name}' updated successfully.")
            return redirect('combo_list')
            
    return render(request, 'core/combo_form.html', {
        'combo': combo,
        'branches': branches,
        'products': products,
        'title': f'Edit Combo: {combo.name}'
    })

@login_required
@transaction.atomic
def combo_delete(request, pk):
    if request.user.role == 'staff':
        messages.error(request, "Access denied. Only Owners and Managers can manage combos.")
        return redirect('dashboard')
    
    combo = get_object_or_404(ComboGroup, pk=pk)
    if request.method == 'POST':
        name = combo.name
        combo.delete()
        messages.success(request, f"Combo '{name}' deleted successfully.")
    return redirect('combo_list')

def combo_offers_public(request):
    # Determine accessible branches; public user can select any branch
    from core.models import Branch
    branches = Branch.objects.all().order_by('name')
    
    selected_branch_id = request.GET.get('branch_id')
    selected_branch = None
    if selected_branch_id:
        selected_branch = get_object_or_404(Branch, id=selected_branch_id)
    elif request.user.is_authenticated and request.user.active_branch:
        selected_branch = request.user.active_branch
        selected_branch_id = str(selected_branch.id)
    elif branches.exists():
        selected_branch = branches.first()
        selected_branch_id = str(selected_branch.id)
        
    combo_groups = []
    if selected_branch:
        combo_groups = ComboGroup.objects.filter(is_active=True, branches=selected_branch).prefetch_related('products', 'tiers')
        
    return render(request, 'billing/combo_offers.html', {
        'branches': branches,
        'selected_branch': selected_branch,
        'combo_groups': combo_groups,
        'csrf_token': request.META.get('CSRF_COOKIE', '')
    })

def get_branch_combo_data(request):
    branch_id = request.GET.get('branch_id')
    if not branch_id:
        return JsonResponse({'error': 'No branch_id provided'}, status=400)
        
    branch = get_object_or_404(Branch, id=branch_id)
    combo_groups = ComboGroup.objects.filter(is_active=True, branches=branch).prefetch_related('products', 'tiers')
    
    # We need to filter products to only those available at this branch (registered in ProductRegistry with stock > 0)
    registries = ProductRegistry.objects.filter(branch=branch, stock_quantity__gt=0).select_related('product')
    available_product_ids = set(r.product_id for r in registries)
    stock_map = {r.product_id: r.stock_quantity for r in registries}
    
    combo_data_list = []
    all_eligible_products = {}
    
    for group in combo_groups:
        tiers = [{'quantity': t.quantity, 'price': float(t.price)} for t in group.tiers.all()]
        # Skip combos with no tiers
        if not tiers:
            continue
            
        group_products = []
        for prod in group.products.all():
            if prod.id in available_product_ids:
                prod_info = {
                    'id': prod.id,
                    'name': prod.name,
                    'barcode': prod.barcode,
                    'price': float(prod.price),
                    'stock': stock_map[prod.id]
                }
                group_products.append(prod_info)
                all_eligible_products[prod.id] = prod_info
                
        if group_products:
            combo_data_list.append({
                'id': group.id,
                'name': group.name,
                'tiers': tiers,
                'product_ids': [p['id'] for p in group_products]
            })
            
    return JsonResponse({
        'combos': combo_data_list,
        'products': list(all_eligible_products.values())
    })
