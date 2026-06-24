from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from decimal import Decimal
from core.models import Branch, Product, ProductRegistry, ComboGroup, ComboTier

def check_combo_barcode_overlap(request, target_branch_ids, selected_barcodes, is_active, exclude_combo_id=None):
    if not selected_barcodes or not is_active:
        return False
    
    overlapping_combos = ComboGroup.objects.filter(
        is_active=True,
        branches__in=target_branch_ids,
        products__barcode__in=selected_barcodes
    )
    if exclude_combo_id:
        overlapping_combos = overlapping_combos.exclude(id=exclude_combo_id)
        
    overlapping_combos = overlapping_combos.prefetch_related('products', 'branches').distinct()
    if overlapping_combos.exists():
        for o_combo in overlapping_combos:
            overlapping_barcodes = set(selected_barcodes) & set(o_combo.products.values_list('barcode', flat=True))
            overlapping_branches = set(target_branch_ids) & set(o_combo.branches.values_list('id', flat=True))
            branch_names = ", ".join(Branch.objects.filter(id__in=overlapping_branches).values_list('name', flat=True))
            barcodes_str = ", ".join(overlapping_barcodes)
            messages.error(
                request,
                f"Barcode(s) '{barcodes_str}' are already assigned to active combo group '{o_combo.name}' ({o_combo.combo_id}) in branch(es): {branch_names}."
            )
        return True
    return False

def calculate_optimal_combo_price(item_prices, tiers_list):
    """
    item_prices: list of floats/Decimals representing base prices of items in the combo.
    tiers_list: list of tuples/dicts with quantity and price, e.g. [(2, 180), (5, 400)]
    Returns the cost to buy all these items, forcing combo tier application when quantity milestone is met.
    """
    prices = sorted([float(p) for p in item_prices], reverse=True)
    n = len(prices)
    # Sort tiers by quantity descending
    sorted_tiers = sorted(tiers_list, key=lambda t: t[0], reverse=True)
    memo = {}

    min_qty = min(qty for qty, _ in sorted_tiers) if sorted_tiers else None

    def solve(index):
        if index >= n:
            return 0.0
        if index in memo:
            return memo[index]

        # Force applying combo tier if remaining quantity satisfies the minimum milestone
        if min_qty is not None and (n - index) >= min_qty:
            best = float('inf')
            for qty, tier_price in sorted_tiers:
                if qty <= n - index:
                    cost = float(tier_price) + solve(index + qty)
                    if cost < best:
                        best = cost
        else:
            # Only fallback to single pricing for leftovers
            best = prices[index] + solve(index + 1)

        memo[index] = best
        return best

    return solve(0)

@login_required
def combo_list(request):
    branches = request.user.get_accessible_branches().order_by('name')
    selected_branch_id = request.GET.get('branch', '')
    q = request.GET.get('q', '').strip()
    
    if request.user.is_owner():
        combos = ComboGroup.objects.all()
    else:
        combos = ComboGroup.objects.filter(branches__in=branches).distinct()
        
    if selected_branch_id:
        combos = combos.filter(branches=selected_branch_id)
        
    if q:
        combos = combos.filter(
            Q(combo_id__icontains=q) | Q(name__icontains=q)
        )
        
    combos = combos.prefetch_related('branches', 'products', 'tiers').order_by('-created_at')
    
    # Paginate by 10
    paginator = Paginator(combos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'core/combo_list.html', {
        'page_obj': page_obj,
        'combos': page_obj.object_list,
        'branches': branches,
        'selected_branch_id': selected_branch_id,
        'q': q,
        'total_branches_count': branches.count(),
    })

@login_required
@transaction.atomic
def combo_create(request):
    if request.user.role != 'owner':
        messages.error(request, "Access denied. Only Owners can manage combos.")
        return redirect('combo_list')
    
    branches = request.user.get_accessible_branches().order_by('name')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        apply_to_all = request.POST.get('apply_to_all_branches') == 'on'
        selected_branches = request.POST.getlist('selected_branches')
        selected_barcodes = request.POST.getlist('products')
        
        tier_quantities = request.POST.getlist('tier_quantity[]')
        tier_prices = request.POST.getlist('tier_price[]')
        
        # Determine target branches
        target_branch_ids = set()
        if apply_to_all:
            target_branch_ids = set(branches.values_list('id', flat=True))
        else:
            for bid_str in selected_branches:
                if bid_str:
                    target_branch_ids.add(int(bid_str))
        
        if not name:
            messages.error(request, "Combo Name is required.")
        elif not target_branch_ids:
            messages.error(request, "Please select at least one branch for availability.")
        elif check_combo_barcode_overlap(request, target_branch_ids, selected_barcodes, is_active):
            pass
        else:
            # Create ComboGroup
            combo = ComboGroup.objects.create(name=name, is_active=is_active)
            combo.branches.set(target_branch_ids)
            
            # Map products by barcode across target branches
            if selected_barcodes:
                all_matching_products = Product.objects.filter(branch_id__in=target_branch_ids, barcode__in=selected_barcodes)
                combo.products.set(all_matching_products)
                

            else:
                combo.products.clear()
                
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
        'selected_branch_ids': set(),
        'selected_products': [],
        'applied_to_all': False,
        'title': 'Create Combo Offer'
    })

@login_required
@transaction.atomic
def combo_edit(request, pk):
    if request.user.role != 'owner':
        messages.error(request, "Access denied. Only Owners can manage combos.")
        return redirect('combo_list')
    
    combo = get_object_or_404(ComboGroup, pk=pk)
    branches = request.user.get_accessible_branches().order_by('name')
    
    all_branch_ids = set(branches.values_list('id', flat=True))
    combo_branch_ids = set(combo.branches.values_list('id', flat=True))
    
    # Check if all branches are selected
    applied_to_all = len(combo_branch_ids) >= len(all_branch_ids) and all_branch_ids.issubset(combo_branch_ids)
    
    selected_products = combo.products.values('name', 'barcode').distinct()
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        
        apply_to_all = request.POST.get('apply_to_all_branches') == 'on'
        selected_branches = request.POST.getlist('selected_branches')
        selected_barcodes = request.POST.getlist('products')
        
        tier_quantities = request.POST.getlist('tier_quantity[]')
        tier_prices = request.POST.getlist('tier_price[]')
        
        # Determine target branches
        target_branch_ids = set()
        if apply_to_all:
            target_branch_ids = set(branches.values_list('id', flat=True))
        else:
            for bid_str in selected_branches:
                if bid_str:
                    target_branch_ids.add(int(bid_str))
        
        if not name:
            messages.error(request, "Combo Name is required.")
        elif not target_branch_ids:
            messages.error(request, "Please select at least one branch for availability.")
        elif check_combo_barcode_overlap(request, target_branch_ids, selected_barcodes, is_active, exclude_combo_id=combo.id):
            pass
        else:
            combo.name = name
            combo.is_active = is_active
            combo.save()
            
            # Update branches
            combo.branches.set(target_branch_ids)
            
            # Find matching products by barcode across target branches
            if selected_barcodes:
                all_matching_products = Product.objects.filter(branch_id__in=target_branch_ids, barcode__in=selected_barcodes)
                combo.products.set(all_matching_products)
                

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
            # Preserve pagination page after edit
            from urllib.parse import urlencode
            page = request.POST.get('page') or request.GET.get('page')
            if page:
                return redirect(f"{reverse('combo_list')}?{urlencode({'page': page})}")
            return redirect('combo_list')
            
    return render(request, 'core/combo_form.html', {
        'combo': combo,
        'branches': branches,
        'selected_branch_ids': combo_branch_ids,
        'selected_products': selected_products,
        'applied_to_all': applied_to_all,
        'title': f'Edit Combo: {combo.name}'
    })

@login_required
def branch_products_ajax(request):
    branch_id = request.GET.get('branch_id')
    q = request.GET.get('q', '').strip()
    if not branch_id:
        return JsonResponse({'products': []})
    
    # Check permissions
    branches = request.user.get_accessible_branches()
    if not request.user.is_owner() and not branches.filter(id=branch_id).exists():
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    if q:
        matching_names = Product.objects.filter(branch_id=branch_id).filter(
            Q(barcode__icontains=q) | Q(name__icontains=q)
        ).values_list('name', flat=True).distinct()
        
        products = Product.objects.filter(branch_id=branch_id, name__in=matching_names).order_by('name')
    else:
        # Return first 20 products initially
        products = Product.objects.filter(branch_id=branch_id).order_by('name')[:20]
        
    product_list = [
        {
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price),
            'branch_id': p.branch_id
        }
        for p in products
    ]
    return JsonResponse({'products': product_list})

@login_required
@transaction.atomic
def combo_delete(request, pk):
    if request.user.role != 'owner':
        messages.error(request, "Access denied. Only Owners can manage combos.")
        return redirect('combo_list')
    
    combo = get_object_or_404(ComboGroup, pk=pk)
    if request.method == 'POST':
        name = combo.name
        combo.delete()
        messages.success(request, f"Combo '{name}' deleted successfully.")
    return redirect('combo_list')

def combo_offers_public(request):
    # Determine accessible branches; public user can select any branch
    from core.models import Branch
    if request.user.is_authenticated:
        branches = request.user.get_accessible_branches().order_by('name')
    else:
        branches = Branch.objects.all().order_by('name')
    
    selected_branch_id = request.GET.get('branch_id')
    selected_branch = None
    if selected_branch_id:
        selected_branch = get_object_or_404(Branch, id=selected_branch_id)
        if request.user.is_authenticated and not request.user.is_owner():
            if selected_branch not in branches:
                selected_branch = branches.first()
                if selected_branch:
                    selected_branch_id = str(selected_branch.id)
                else:
                    selected_branch_id = None
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
    if request.user.is_authenticated and not request.user.is_owner():
        if branch not in request.user.get_accessible_branches():
            return JsonResponse({'error': 'Permission denied'}, status=403)
            
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

@login_required
def global_products_ajax(request):
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'products': []})
        
    products = Product.objects.filter(
        Q(barcode__icontains=q) | Q(name__icontains=q)
    ).values('name', 'barcode').distinct()[:30]
    
    product_list = [
        {
            'barcode': p['barcode'],
            'name': p['name'],
            'label': f"{p['name']} ({p['barcode']})"
        }
        for p in products
    ]
    return JsonResponse({'products': product_list})
