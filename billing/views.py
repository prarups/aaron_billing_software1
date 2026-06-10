from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .forms import ReturnCreateForm
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
from django.utils import timezone
from django.db.models import Sum, Count, F, Subquery, OuterRef
from core.models import Product, ProductRegistry, StockTransaction
from .models import Bill, BillItem, ReturnRequest, CreditNote
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
    
    return render(request, 'pos/index.html', {
        'registrations': registrations,
        'edit_cart_data_json': json.dumps(edit_cart_data) if edit_cart_data else 'null'
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
            
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'barcode': product.barcode,
            'price': float(product.price),
            'stock': stock,
            'combos': [{'quantity': c.quantity, 'price': float(c.price)} for c in product.combos.filter(branch=request.user.active_branch).order_by('-quantity')]
        })
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

@login_required
@transaction.atomic
def return_create_view(request):
    if request.method == 'POST':
        form = ReturnCreateForm(request.POST)
        if form.is_valid():
            import json
            # Parse selected return items sent as JSON
            return_items_json = request.POST.get('return_items', '[]')
            try:
                return_items = json.loads(return_items_json)
            except json.JSONDecodeError:
                return_items = []
                        # Process each returned item with its own condition and action
            for item_data in return_items:
                try:
                    bill_item = BillItem.objects.select_related('product').get(id=item_data['id'])
                except BillItem.DoesNotExist:
                    continue
                qty = int(item_data.get('quantity', 1))
                condition = item_data.get('condition', form.cleaned_data['condition'])
                action_type = item_data.get('action_type', form.cleaned_data['action_type'])
                reason = form.cleaned_data['reason']
                # Create ReturnRequest per item
                ret = ReturnRequest.objects.create(
                    invoice=form.cleaned_data['invoice_id'],
                    bill_item=bill_item,
                    product=bill_item.product,
                    quantity=qty,
                    condition=condition,
                    action_type=action_type,
                    requested_by=request.user,
                    product_name=bill_item.product.name,
                    reason=reason,
                    status=ReturnRequest.Status.APPROVED,
                    active_branch=request.user.active_branch,
                )
                # Credit note per item – only for refunds
                if action_type == 'REFUND':
                    CreditNote.objects.create(
                        invoice=form.cleaned_data['invoice_id'],
                        amount=bill_item.unit_price * qty,
                        reason=reason,
                        issued_by=request.user,
                    )
                # Update stock
                _process_stock(ret, request.user)
            # Old per-item loop removed (handled above)

            messages.success(request, f"Processed {len(return_items)} returned item(s) for Invoice {form.cleaned_data['invoice_id'].invoice_number or form.cleaned_data['invoice_id'].id}.")
            return redirect('stock_pivot_report')
    else:
        initial = {}
        invoice_id = request.GET.get('invoice_id')
        if invoice_id:
            initial['invoice_id'] = invoice_id
        form = ReturnCreateForm(initial=initial)
    return render(request, 'billing/return_create.html', {'form': form})

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
            retail_price = data.get('retail_price', data.get('discount_amount', 0))
            
            if not items:
                return JsonResponse({'error': 'Cart is empty'}, status=400)
            
            with transaction.atomic():
                if editing_bill_id:
                    # Retrieve existing bill for modification
                    bill = get_object_or_404(Bill, id=editing_bill_id)
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
                    
                    # Calculate subtotal with combos
                    qty_remaining = quantity
                    subtotal = 0
                    combos = product.combos.filter(branch=bill.branch).order_by('-quantity')
                    for combo in combos:
                        if qty_remaining >= combo.quantity and combo.quantity > 0:
                            num_combos = qty_remaining // combo.quantity
                            subtotal += num_combos * combo.price
                            qty_remaining %= combo.quantity
                    subtotal += qty_remaining * product.price

                    effective_unit_price = subtotal / quantity if quantity > 0 else 0

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
                
                total_amount = float(subtotal_amount) + float(retail_price)
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
    # Check permissions
    if not request.user.is_superuser and bill.branch != request.user.active_branch:
        return HttpResponse("Unauthorized to edit this bill.", status=403)
        
    # Check if editing is allowed (only allowed if it was the last generated bill)
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
        combos_list = [{'quantity': c.quantity, 'price': float(c.price)} for c in item.product.combos.filter(branch=bill.branch).order_by('-quantity')]

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
    public_url = request.build_absolute_uri(f"/billing/share/{bill.share_id}/")
    wa_lines = [f"*Bill {bill.invoice_number or bill.id} - {bill.branch.name}*"]
    wa_lines.append(f"View/Download Bill: {public_url}")
    wa_text = "%0A".join(wa_lines)
    wa_link = f"https://wa.me/{bill.customer_phone}?text={wa_text}" if bill.customer_phone else None
    
    # Check if this bill was just created in the current session and redirected from POS
    from_pos = request.GET.get('from_pos') == 'true'
    newly_created_id = request.session.get('newly_created_bill_id')
    allow_edit = from_pos and (newly_created_id == bill.id)
    
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
    
    # Restricted query for Managers
    accessible_branches = request.user.get_accessible_branches()
    bills = Bill.objects.filter(branch__in=accessible_branches).order_by('-created_at').select_related('branch', 'staff').prefetch_related('items__product', 'return_requests__product')
    
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
                branch_id = str(request.user.active_branch.id)
        else:
            # Default to active branch if no valid filter
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
    
    # Annotate each bill on the current page with return data
    for bill in page_obj:
        returns_qs = bill.return_requests.filter(status=ReturnRequest.Status.APPROVED)
        bill.return_amount = sum([(ret.quantity * (ret.product.price if ret.product else 0)) for ret in returns_qs if ret.action_type == 'REFUND'])
        bill.return_reason = ", ".join(set([ret.reason for ret in returns_qs if ret.reason]))
        bill.returned_items_list = [{
            'name': ret.product_name,
            'barcode': ret.product.barcode if ret.product else 'N/A',
            'quantity': ret.quantity,
            'price': float(ret.product.price) if ret.product else 0,
            'total': float(ret.quantity * (ret.product.price if ret.product else 0)),
            'condition': ret.get_condition_display(),
            'action': ret.get_action_type_display(),
        } for ret in returns_qs]
        bill.has_returns = len(bill.returned_items_list) > 0
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
    bills = Bill.objects.filter(branch__in=accessible_branches).order_by('-created_at').select_related('branch', 'staff').prefetch_related('items__product', 'return_requests')
    
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
        # Aggregate return data
        returns_qs = bill.return_requests.filter(status=ReturnRequest.Status.APPROVED)
        total_return_amount = sum([ (ret.quantity * (ret.product.price if ret.product else 0)) for ret in returns_qs if ret.action_type == 'REFUND' ])
        return_reason = ", ".join(set([ret.reason for ret in returns_qs if ret.reason]))
        returned_items = ", ".join([f"{ret.product_name} [{ret.product.barcode if ret.product else 'N/A'}] x{ret.quantity} @₹{ret.product.price if ret.product else 0}/ea ({ret.get_condition_display()}/{ret.get_action_type_display()})" for ret in returns_qs])
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
