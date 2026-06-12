from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
from django.utils import timezone
from django.db.models import Sum, Count, F, Subquery, OuterRef
from core.models import Product, ProductRegistry, StockTransaction
from .models import Bill, BillItem
import json
import csv

@login_required
def pos_index(request):
    # Auto-initialize active branch if None
    if not request.user.active_branch:
        accessible = request.user.get_accessible_branches()
        if accessible.exists():
            request.user.active_branch = accessible.first()
            request.user.save()

    # Fetch registry for active branch
    registrations = ProductRegistry.objects.filter(
        branch=request.user.active_branch
    ).select_related('product').prefetch_related('product__combos')
    
    # Check for edit cart data in session
    edit_cart_data = request.session.pop('pos_edit_cart', None)
    
    # Fetch active combo groups for this branch so the POS can apply live combo pricing
    from core.models import ComboGroup
    combo_groups_data = []
    if request.user.active_branch:
        active_groups = ComboGroup.objects.filter(
            is_active=True, branches=request.user.active_branch
        ).prefetch_related('products', 'tiers')
        for grp in active_groups:
            tiers = [{'quantity': t.quantity, 'price': float(t.price)} for t in grp.tiers.all()]
            if not tiers:
                continue
            combo_groups_data.append({
                'id': grp.id,
                'name': grp.name,
                'tiers': tiers,
                'product_ids': [str(p.id) for p in grp.products.all()],
            })
    
    return render(request, 'pos/index.html', {
        'registrations': registrations,
        'edit_cart_data_json': json.dumps(edit_cart_data) if edit_cart_data else 'null',
        'combo_groups_json': json.dumps(combo_groups_data),
    })

@login_required
def get_product_by_barcode(request):
    barcode = request.GET.get('barcode')
    if not barcode:
        return JsonResponse({'error': 'No barcode provided'}, status=400)
    
    try:
        product = Product.objects.get(barcode=barcode, branch=request.user.active_branch)
        try:
            registry = ProductRegistry.objects.get(product=product, branch=request.user.active_branch)
            stock = registry.stock_quantity
        except ProductRegistry.DoesNotExist:
            stock = 0
            
        combos_qs = product.combos.filter(branch=request.user.active_branch).order_by('-quantity')

        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'price': float(product.price),
            'stock': stock,
            'combos': [{'quantity': c.quantity, 'price': float(c.price)} for c in combos_qs],
        })
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required
@transaction.atomic
def process_bill(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            editing_bill_id = data.get('editing_bill_id')
            items = data.get('items', [])
            customer_name = data.get('customer_name', '')
            customer_phone = data.get('customer_phone', '')
            payment_method = data.get('payment_method', 'cash')
            cash_amount = data.get('cash_amount', 0)
            online_amount = data.get('online_amount', 0)

            retail_price = data.get('retail_price', 0)
            
            if not items:
                return JsonResponse({'error': 'Cart is empty'}, status=400)
            
            with transaction.atomic():
                if editing_bill_id:
                    # Retrieve existing bill for modification
                    bill = get_object_or_404(Bill, id=editing_bill_id)
                    
                    # Double-check authorization to edit
                    can_edit = request.user.role == 'owner' or getattr(request.user, 'has_bill_edit_rights', False)
                    is_newly_created = request.session.get('newly_created_bill_id') == bill.id
                    if not (can_edit or is_newly_created):
                        return JsonResponse({'error': 'Unauthorized to edit this bill.'}, status=403)
                    # Revert stock quantities of old items
                    for old_item in bill.items.all():
                        try:
                            reg = ProductRegistry.objects.get(product=old_item.product, branch=bill.branch)
                            reg.stock_quantity += old_item.quantity
                            reg.save()
                        except ProductRegistry.DoesNotExist:
                            pass
                    # Delete old stock transactions
                    StockTransaction.objects.filter(
                        branch=bill.branch,
                        reference=f"Bill {bill.invoice_number}"
                    ).delete()
                    # Delete old bill items
                    bill.items.all().delete()
                    
                    # Update bill properties
                    bill.staff = request.user
                    bill.customer_name = customer_name
                    bill.customer_phone = customer_phone
                    bill.payment_method = payment_method
                    bill.cash_amount = cash_amount
                    bill.online_amount = online_amount
                    bill.retail_price = retail_price

                else:
                    # Create a new Bill
                    bill = Bill.objects.create(
                        branch=request.user.active_branch,
                        staff=request.user,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        total_amount=0,  # Will update after items
                        payment_method=payment_method,
                        cash_amount=cash_amount,
                        online_amount=online_amount,
                        retail_price=retail_price
                    )
                
                subtotal_amount = 0
                retail_price_total = 0
                resolved_items = []
                for item in items:
                    product = get_object_or_404(Product, id=item['id'])
                    quantity = int(item['quantity'])
                    
                    # Stock logic - restored
                    registry = get_object_or_404(ProductRegistry, product=product, branch=request.user.active_branch)
                    if registry.stock_quantity < quantity:
                        raise ValueError(f"Insufficient stock for {product.name} at {request.user.active_branch.name}. Available: {registry.stock_quantity}")
                    
                    # Decrement stock
                    registry.stock_quantity -= quantity
                    registry.save()
                    
                    resolved_items.append({
                        'product': product,
                        'quantity': quantity,
                    })

                # Now calculate subtotals and unit prices using multi-product combo groups first, then fallback to individual combos
                from core.combo_views import calculate_optimal_combo_price, ComboGroup
                from decimal import Decimal
                
                # Fetch active combo groups for this branch
                active_combo_groups = ComboGroup.objects.filter(is_active=True, branches=bill.branch).prefetch_related('products', 'tiers')
                processed_items = set()
                
                for group in active_combo_groups:
                    group_tiers = [(t.quantity, t.price) for t in group.tiers.all()]
                    if not group_tiers:
                        continue
                    
                    # Find resolved items belonging to this combo group that haven't been processed
                    group_cart_items = []
                    for r_item in resolved_items:
                        p = r_item['product']
                        if p.id not in processed_items and group.products.filter(id=p.id).exists():
                            group_cart_items.append(r_item)
                            
                    if not group_cart_items:
                        continue
                        
                    # Expand items to get individual base prices
                    expanded_prices = []
                    for r_item in group_cart_items:
                        p = r_item['product']
                        qty = r_item['quantity']
                        for _ in range(qty):
                            expanded_prices.append(float(p.price))
                            
                    if not expanded_prices:
                        continue
                        
                    # Calculate optimal combo price
                    optimal_price = calculate_optimal_combo_price(expanded_prices, group_tiers)
                    
                    # Distribute the optimal price proportionally
                    regular_total = sum(expanded_prices)
                    discount_ratio = float(optimal_price) / regular_total if regular_total > 0 else 1.0
                    
                    allocated_subtotals = []
                    sum_allocated = 0
                    
                    for r_item in group_cart_items:
                        qty = r_item['quantity']
                        p = r_item['product']
                        item_regular_subtotal = float(p.price * qty)
                        item_allocated_subtotal = round(item_regular_subtotal * discount_ratio)
                        allocated_subtotals.append(item_allocated_subtotal)
                        sum_allocated += item_allocated_subtotal
                        
                    # Adjust rounding difference on the first item
                    diff = round(float(optimal_price)) - sum_allocated
                    if diff != 0 and len(allocated_subtotals) > 0:
                        allocated_subtotals[0] += diff
                        
                    # Save the results in resolved_items dict
                    for idx, r_item in enumerate(group_cart_items):
                        sub = allocated_subtotals[idx]
                        qty = r_item['quantity']
                        r_item['subtotal'] = Decimal(str(sub))
                        r_item['unit_price'] = float(sub / qty) if qty > 0 else 0
                        processed_items.add(r_item['product'].id)
                
                # Fallback for remaining items
                for r_item in resolved_items:
                    p = r_item['product']
                    if p.id in processed_items:
                        continue
                        
                    qty = r_item['quantity']
                    qty_remaining = qty
                    subtotal = 0
                    combos = p.combos.filter(branch=bill.branch).order_by('-quantity')
                    for combo in combos:
                        if qty_remaining >= combo.quantity and combo.quantity > 0:
                            num_combos = qty_remaining // combo.quantity
                            subtotal += num_combos * combo.price
                            qty_remaining %= combo.quantity
                    subtotal += qty_remaining * p.price
                    
                    r_item['subtotal'] = subtotal
                    r_item['unit_price'] = float(subtotal / qty) if qty > 0 else 0


                # Phase 3: Create BillItems, log StockTransactions, and sum subtotals
                for r_item in resolved_items:
                    product = r_item['product']
                    quantity = r_item['quantity']
                    subtotal = r_item['subtotal']
                    effective_unit_price = r_item['unit_price']
                    
                    bill_item = BillItem.objects.create(
                        bill=bill,
                        product=product,
                        quantity=quantity,
                        unit_price=effective_unit_price,
                        subtotal=subtotal,
                    )
                    
                    # Log Stock Transaction
                    StockTransaction.objects.create(
                        product=product,
                        branch=request.user.active_branch,
                        transaction_type='OUT',
                        quantity=quantity,
                        reference=f"Bill {bill.invoice_number}",
                        user=request.user
                    )
                    
                    subtotal_amount += bill_item.subtotal
                
                total_amount = float(subtotal_amount) + float(bill.retail_price)
                if total_amount < 0:
                    total_amount = 0
                    
                bill.total_amount = total_amount
                
                # Validation for payment amounts
                if payment_method == 'cash':
                    bill.cash_amount = total_amount
                    bill.online_amount = 0
                elif payment_method == 'online':
                    bill.online_amount = total_amount
                    bill.cash_amount = 0
                elif payment_method == 'split':
                    if float(cash_amount) + float(online_amount) != float(total_amount):
                        raise ValueError(f"Split amounts (₹{cash_amount} + ₹{online_amount}) do not match total ₹{total_amount}")
                
                bill.save()
                
            request.session['newly_created_bill_id'] = bill.id
            request.session.pop('exchange_customer', None)  # Clear exchange info after successful billing
            return JsonResponse({'success': True, 'bill_id': bill.id})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
            
    return JsonResponse({'error': 'Invalid request'}, status=405)

@login_required
@transaction.atomic
def update_customer_details(request, bill_id):
    if request.method == 'POST':
        bill = get_object_or_404(Bill, id=bill_id)
        if not request.user.is_superuser and bill.branch != request.user.active_branch:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        data = json.loads(request.body)
        bill.customer_name = data.get('customer_name', bill.customer_name)
        bill.customer_phone = data.get('customer_phone', bill.customer_phone)
        bill.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid request'}, status=405)

@login_required
def edit_bill_back(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)
    # Check permissions (branch ownership)
    if not request.user.is_superuser and bill.branch != request.user.active_branch:
        return HttpResponse("Unauthorized to edit this bill.", status=403)

    # Restrict editing to the same calendar day as bill creation (applies to all users, including admin)
    from django.utils import timezone
    if bill.created_at.date() != timezone.now().date():
        return HttpResponse("Editing is only allowed on the same day the bill was created.", status=403)

    # Existing permission check: allow owners or users with explicit edit rights
    can_edit = request.user.role == 'owner' or getattr(request.user, 'has_bill_edit_rights', False)
    # Allow editing from POS interface (e.g., when a staff is actively billing) via a query flag
    from_pos = request.GET.get('from_pos') == 'true'
    if from_pos:
        can_edit = True
    if not can_edit:
        # Also allow if this is the bill just created in the current session
        if request.session.get('newly_created_bill_id') != bill.id:
            return HttpResponse("Editing is only allowed immediately after generating the bill.", status=403)
            
    items_data = []
    for item in bill.items.all():
        # Get current registry stock
        current_stock = 0
        try:
            current_stock = ProductRegistry.objects.get(product=item.product, branch=bill.branch).stock_quantity
        except ProductRegistry.DoesNotExist:
            pass

        # Fetch combos
        combos_qs = item.product.combos.filter(branch=bill.branch).order_by('-quantity')
        combos_list = [{'quantity': c.quantity, 'price': float(c.price)} for c in combos_qs]

        items_data.append({
            'id': str(item.product.id),
            'name': item.product.name,
            'barcode': item.product.barcode,
            'price': float(item.product.price),
            'quantity': item.quantity,
            'stock': current_stock + item.quantity, # virtual stock including this bill's items
            'combos': combos_list,
        })
        
    # Store in session
    request.session['pos_edit_cart'] = {
        'editing_bill_id': bill.id,
        'invoice_number': bill.invoice_number or f"#{bill.id}",
        'items': items_data,
        'customer_name': bill.customer_name or '',
        'customer_phone': bill.customer_phone or '',
        'payment_method': bill.payment_method,
        'retail_price': float(bill.retail_price),
        'cash_amount': float(bill.cash_amount),
        'online_amount': float(bill.online_amount),
    }
    
    return redirect('pos_index')

@login_required
def bill_detail(request, bill_id):
    """Show a web-based bill receipt with download & WhatsApp buttons."""
    # Ensure user can only see bills from their active branch
    bill = get_object_or_404(Bill, id=bill_id)
    if not request.user.is_superuser and bill.branch != request.user.active_branch:
        return HttpResponse("Unauthorized to view this bill.", status=403)
    items = bill.items.select_related('product').all()
    # Build WhatsApp message text
    import urllib.parse
    public_url = request.build_absolute_uri(f"/billing/share/{bill.share_id}/")
    wa_lines = [
        f"*Bill {bill.invoice_number or bill.id} - {bill.branch.name}*",
        f"View/Download Bill: {public_url}",
        "Follow us on Instagram: https://www.instagram.com/aaron_garments?igsh=YWpkdWE0emkyZjNv"
    ]
    wa_text = "\n".join(wa_lines)
    # Normalize phone number: strip non-digits and ensure it has a country code (default to '91' for India)
    def normalize_phone(phone: str) -> str:
        digits = ''.join(filter(str.isdigit, phone))
        # If the number starts with a country code (e.g., 1-3 digits) and length > 10, keep as is
        if len(digits) > 10:
            return digits
        # Otherwise, prepend default country code (you may adjust as needed)
        return f"91{digits}" if digits else ''
    normalized_phone = normalize_phone(bill.customer_phone) if bill.customer_phone else ''
    encoded_text = urllib.parse.quote(wa_text)
    wa_link = f"https://wa.me/{normalized_phone}?text={encoded_text}" if normalized_phone else None
    
    # Check if this bill was just created in the current session and redirected from POS
    from_pos = request.GET.get('from_pos') == 'true'
    newly_created_id = request.session.get('newly_created_bill_id')
    can_edit = request.user.role == 'owner' or getattr(request.user, 'has_bill_edit_rights', False)
    allow_edit = can_edit or (from_pos and (newly_created_id == bill.id))
    
    # Build items list with barcode formatting for Code39 font
    items = list(items)
    for it in items:
        raw_bc = it.product.barcode or ''
        # Replace spaces with hyphens (safe delimiter) and wrap with asterisks as required by Code39
        safe_bc = raw_bc.replace(' ', '-')
        it.barcode_display = f"*{safe_bc}*"

    return render(request, 'billing/bill_detail.html', {
        'bill': bill,
        'items': items,
        'wa_link': wa_link,
        'public_url': public_url,
        'allow_edit': allow_edit
    })

def public_bill_detail(request, share_id):
    """Publicly accessible bill view for customers (no login required)."""
    bill = get_object_or_404(Bill, share_id=share_id)
    items = bill.items.select_related('product').all()
    # Prepare barcode for Code39: replace spaces with hyphens and wrap with asterisks
    items = list(items)
    for it in items:
        raw = it.product.barcode or ''
        safe = raw.replace(' ', '-')
        it.barcode_display = f"*{safe}*"
    # Build items list with barcode formatting for Code39 font
    items = list(items)
    for it in items:
        raw_bc = it.product.barcode or ''
        safe_bc = raw_bc.replace(' ', '-')
        it.barcode_display = f"*{safe_bc}*"

    return render(request, 'billing/public_bill_detail.html', {
        'bill': bill,
        'items': items,
    })

@login_required
def staff_activity(request):
    request.session.pop('newly_created_bill_id', None)
    date_str = request.GET.get('date', timezone.now().date().isoformat())
    try:
        target_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        target_date = timezone.now().date()
    
    # Filter bills for the logged-in staff at their active branch on the target date
    bills = Bill.objects.filter(
        staff=request.user,
        branch=request.user.active_branch,
        created_at__date=target_date
    ).order_by('-created_at').prefetch_related('items__product')
    
    # Aggregates
    stats = bills.aggregate(
        total_sales=Sum('total_amount'),
        transaction_count=Count('id')
    )
    
    # Items summary
    items_sold = BillItem.objects.filter(
        bill__in=bills
    ).values('product__name').annotate(total_qty=Sum('quantity')).order_by('-total_qty')

    context = {
        'bills': bills,
        'stats': stats,
        'items_sold': items_sold,
        'target_date': target_date.isoformat(),
        'today': timezone.now().date().isoformat(),
    }
    return render(request, 'billing/staff_activity.html', context)

@login_required
def owner_bill_list(request):
    """A comprehensive list of all bills for Owners and Managers."""
    request.session.pop('newly_created_bill_id', None)
    if request.user.role == 'staff':
        return HttpResponse("Unauthorized", status=403)
    
    # Ensure active_branch is set for manager/owner
    if not request.user.active_branch:
        accessible = request.user.get_accessible_branches()
        if accessible.exists():
            request.user.active_branch = accessible.first()
            request.user.save()
    # Restricted query for Managers
    accessible_branches = request.user.get_accessible_branches()
    bills = Bill.objects.filter(branch__in=accessible_branches).order_by('-created_at').select_related('branch', 'staff').prefetch_related('items__product')
    
    # Filter by active branch if manager
    if request.user.role == 'manager':
        # Default to active branch if no filter chosen, but the base query above already restricts to accessible branches
        pass
    
    # Filters from GET
    q = request.GET.get('q', '')
    branch_id = request.GET.get('branch')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    payment_method = request.GET.get('payment_method')
    
    # Handle search
    if q:
        from django.db.models import Q
        bills = bills.filter(
            Q(id__icontains=q) | 
            Q(invoice_number__icontains=q) | 
            Q(customer_name__icontains=q) | 
            Q(customer_phone__icontains=q)
        )
    
    # Handle branch restriction
    if request.user.role == 'manager':
        branches = request.user.get_accessible_branches()
        # Ensure they can only filter branches they manage
        if branch_id and branch_id != 'None':
            if not branches.filter(id=branch_id).exists():
                if request.user.active_branch:
                    branch_id = str(request.user.active_branch.id)
        else:
            # Default to active branch if no valid filter and active_branch exists
            if request.user.active_branch:
                branch_id = str(request.user.active_branch.id)
    else:
        from core.models import Branch
        branches = Branch.objects.all()

    if branch_id and branch_id != 'None':
        bills = bills.filter(branch_id=branch_id)
    if start_date and start_date != 'None':
        bills = bills.filter(created_at__date__gte=start_date)
    if end_date and end_date != 'None':
        bills = bills.filter(created_at__date__lte=end_date)
    if payment_method and payment_method != 'None':
        bills = bills.filter(payment_method=payment_method)
        
    # Stats for the filtered selection
    stats = bills.aggregate(
        total_revenue=Sum('total_amount'),
        bill_count=Count('id')
    )
    
    from django.core.paginator import Paginator
    paginator = Paginator(bills, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'branches': branches,
        'selected_branch': branch_id,
        'start_date': start_date,
        'end_date': end_date,
        'selected_payment': payment_method,
        'query': q,
    }
    return render(request, 'billing/owner_bill_list.html', context)

@login_required
def export_sales_csv(request):
    # Only Owners and Managers can export
    if request.user.role == 'staff':
        return HttpResponse("Unauthorized", status=403)
        
    now = timezone.now()
    # Format: 2026-03-30_12-47-29
    timestamp = now.strftime('%Y-%m-%d_%H-%M-%p') # added AM/PM for better clarity if user prefers
    filename = f"sales_report_{timestamp}.csv"
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow(['Invoice Number', 'Branch Name', 'Branch Code', 'Staff', 'Customer', 'Phone', 'Total Amount', 'Retail Price', 'Cash', 'Online', 'Payment Method', 'Purchased Items', 'Return Amount', 'Return Reason', 'Returned Items', 'Date & Time'])
    
    # Build base queryset
    accessible_branches = request.user.get_accessible_branches()
    bills = Bill.objects.filter(branch__in=accessible_branches).order_by('-created_at').select_related('branch', 'staff').prefetch_related('items__product')
    
    q = request.GET.get('q', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    branch_id = request.GET.get('branch', '')
    payment_method = request.GET.get('payment_method', '')

    if q:
        from django.db.models import Q
        bills = bills.filter(
            Q(id__icontains=q) | 
            Q(invoice_number__icontains=q) | 
            Q(customer_name__icontains=q) | 
            Q(customer_phone__icontains=q)
        )
        
    if request.user.role == 'manager':
        branches = request.user.get_accessible_branches()
        if branch_id and branch_id != 'None':
            if not branches.filter(id=branch_id).exists():
                branch_id = str(request.user.active_branch.id)
        else:
            branch_id = str(request.user.active_branch.id)
            
    if branch_id and branch_id != 'None':
        bills = bills.filter(branch_id=branch_id)
        
    if start_date and start_date != 'None':
        bills = bills.filter(created_at__date__gte=start_date)
    if end_date and end_date != 'None':
        bills = bills.filter(created_at__date__lte=end_date)
    if payment_method and payment_method != 'None':
        bills = bills.filter(payment_method=payment_method)
        
    for bill in bills.select_related('branch', 'staff'):
        purchased_items = ", ".join([f"{item.product.name} ({item.product.barcode}) x{item.quantity}" for item in bill.items.all()])
        # Return data is deactivated
        total_return_amount = 0
        return_reason = ""
        returned_items = ""
        writer.writerow([
            bill.invoice_number,
            bill.branch.name if bill.branch else 'N/A',
            bill.branch.code if bill.branch else 'N/A',
            bill.staff.username if bill.staff else 'N/A',
            bill.customer_name or 'Guest',
            bill.customer_phone or '',
            bill.total_amount,
            bill.retail_price,
            bill.cash_amount,
            bill.online_amount,
            bill.get_payment_method_display(),
            purchased_items,
            f"{total_return_amount:.2f}" if total_return_amount else '',
            return_reason,
            returned_items,
            bill.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return response

@login_required
def clear_exchange_session(request):
    """AJAX endpoint to clear the exchange_customer session state."""
    request.session.pop('exchange_customer', None)
    return JsonResponse({'success': True})
