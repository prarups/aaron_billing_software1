from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from .forms import ReturnCreateForm
from .models import Bill, BillItem
from core.models import ProductRegistry, StockTransaction, StockAdjustment

def _get_bill_items_data(bill, max_items=None):
    from .return_models import ReturnRequest
    from django.db.models import Sum
    from core.models import ComboGroup, ProductRegistry, Product

    bill_items = []
    too_many_items = False
    
    items_qs = bill.items.select_related("product").all()
    items_list = list(items_qs)
    
    if max_items and len(items_list) > max_items:
        too_many_items = True
        items_list = items_list[:max_items]

    if not items_list:
        return [], False

    item_ids = [item.id for item in items_list]
    product_ids = [item.product_id for item in items_list]

    approved_returns = ReturnRequest.objects.filter(
        bill_item_id__in=item_ids,
        status=ReturnRequest.Status.APPROVED
    ).values('bill_item').annotate(total=Sum('quantity'))
    returned_qty_map = {r['bill_item']: r['total'] for r in approved_returns}

    combo_groups = ComboGroup.objects.filter(
        products__id__in=product_ids,
        branches=bill.branch,
        is_active=True
    ).prefetch_related('products', 'tiers').distinct()

    combo_map = {}
    combo_product_ids = set()
    for cg in combo_groups:
        for p in cg.products.all():
            combo_product_ids.add(p.id)
            if p.id not in combo_map:
                combo_map[p.id] = cg

    if combo_product_ids:
        # Combo groups might link to Product instances from other branches.
        # We need to find the stock for the equivalent barcode at the bill's branch.
        combo_products = Product.objects.filter(id__in=combo_product_ids)
        barcodes = [p.barcode for p in combo_products if p.barcode]
        
        registries = ProductRegistry.objects.filter(
            product__barcode__in=barcodes,
            branch=bill.branch
        ).select_related('product')
        
        barcode_stock_map = {reg.product.barcode: reg.stock_quantity for reg in registries}
        
        stock_map = {}
        for p in combo_products:
            stock_map[p.id] = barcode_stock_map.get(p.barcode, 0)
    else:
        stock_map = {}
        
    combo_total_qty = {}
    for item in list(items_qs):
        cg = combo_map.get(item.product_id)
        if cg:
            combo_total_qty[cg.id] = combo_total_qty.get(cg.id, 0) + item.quantity

    for item in items_list:
        returned_qty = returned_qty_map.get(item.id, 0)
        remaining_qty = max(0, item.quantity - returned_qty)
        
        cg = combo_map.get(item.product_id)
        is_combo = False
        combo_name = ""
        combo_eligible_product_ids = []
        combo_tiers = []
        combo_eligible_products = []
        
        if cg:
            min_combo_qty = min([t.quantity for t in cg.tiers.all()]) if cg.tiers.all() else 1
            if combo_total_qty.get(cg.id, 0) >= min_combo_qty:
                is_combo = True
                combo_name = cg.name
                combo_eligible_product_ids = [p.id for p in cg.products.all()]
                combo_tiers = [f"{t.quantity} items → ₹{t.price:.0f}" for t in cg.tiers.all()]
                for p in cg.products.all():
                    stock = stock_map.get(p.id, 0)
                    combo_eligible_products.append({
                        "id": p.id,
                        "name": p.name,
                        "barcode": p.barcode,
                        "price": int(p.price),
                        "stock": stock
                    })
        
        bill_items.append({
            "id": item.id,
            "product_id": item.product.id,
            "product_name": item.product.name,
            "product_barcode": item.product.barcode,
            "quantity": item.quantity,
            "returned_quantity": returned_qty,
            "remaining_quantity": remaining_qty,
            "unit_price": int(item.unit_price),
            "is_combo": is_combo,
            "combo_name": combo_name,
            "combo_eligible_product_ids": combo_eligible_product_ids,
            "combo_tiers": combo_tiers,
            "combo_eligible_products": combo_eligible_products,
        })
        
    return bill_items, too_many_items


@login_required
@never_cache
def return_create_view(request):
    """Handle product return creation.
    GET: display form with optional pre‑filled invoice ID and bill items.
    POST: validate form, process returns, and redirect on success.
    """
    from .return_models import ReturnRequest
    from django.db.models import Sum

    bill = None

    # ---------- POST handling ----------
    return_confirmed = False
    redirect_url = ""
    success_message = ""
    if request.method == "POST":
        form = ReturnCreateForm(request.POST, user=request.user)
        if form.is_valid():
            returns = form.save(request.user)
            return_confirmed = True
            success_message = f"Processed {len(returns)} returned item(s) successfully."
            redirect_url_name = "staff_activity" if request.user.role == 'sales_staff' else "owner_bill_list"
            from django.urls import reverse
            redirect_url = reverse(redirect_url_name)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        # ---------- GET handling ----------
        initial = {}
        invoice_id = request.GET.get("invoice_id")
        if invoice_id:
            try:
                invoice_id_str = str(invoice_id).strip()
                bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
                if not bill and invoice_id_str.isdigit():
                    bill = Bill.objects.get(id=int(invoice_id_str))
                if bill and not request.user.is_superuser and bill.branch != request.user.active_branch:
                    bill = None
                if bill:
                    initial["invoice_id"] = bill.invoice_number or str(bill.id)
                else:
                    initial["invoice_id"] = invoice_id
            except Bill.DoesNotExist:
                initial["invoice_id"] = invoice_id
        form = ReturnCreateForm(initial=initial, user=request.user)

    # ---------- Prepare bill items JSON for the template ----------
    import json
    bill_items_json = "[]"
    invoice_id = request.GET.get("invoice_id") or request.POST.get("invoice_id")
    if invoice_id:
        try:
            invoice_id_str = str(invoice_id).strip()
            bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
            if not bill and invoice_id_str.isdigit():
                bill = Bill.objects.get(id=int(invoice_id_str))
            
            if bill and not request.user.is_superuser and bill.branch != request.user.active_branch:
                bill = None
            
            if bill:
                bill_items, too_many_items = _get_bill_items_data(bill, max_items=200)
                bill_items_json = json.dumps(bill_items)
                request.session['too_many_items'] = too_many_items
            else:
                bill_items_json = "[]"
        except (Bill.DoesNotExist, ValueError):
            pass

    target_branch_id = ""
    if bill:
        target_branch_id = bill.branch.id
    elif request.user.is_authenticated and request.user.active_branch:
        target_branch_id = request.user.active_branch.id

    all_products_json = "[]"

    selected_bill_item = form.data.get("bill_item") if form.is_bound else ""
    selected_quantity = form.data.get("quantity") if form.is_bound else 1
    selected_condition = form.data.get("condition") if form.is_bound else "GOOD"
    selected_action_type = form.data.get("action_type") if form.is_bound else "EXCH_SAME"

    return render(request, "billing/return_form.html", {
        "form": form,
        "bill_items_json": bill_items_json,
        "all_products_json": all_products_json,
        "target_branch_id": target_branch_id,
        "selected_bill_item": selected_bill_item,
        "selected_quantity": selected_quantity,
        "selected_condition": selected_condition,
        "selected_action_type": selected_action_type,
        "return_confirmed": return_confirmed,
        "redirect_url": redirect_url,
        "success_message": success_message,
    })


@login_required
@never_cache
def get_bill_items_api(request):
    """AJAX endpoint: returns bill items for a given invoice ID including return history details."""
    from .return_models import ReturnRequest
    from django.db.models import Sum

    invoice_id = request.GET.get("invoice_id")
    if not invoice_id:
        return JsonResponse({"items": []})
    try:
        invoice_id_str = str(invoice_id).strip()
        bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
        if not bill and invoice_id_str.isdigit():
            bill = Bill.objects.get(id=int(invoice_id_str))
    except (Bill.DoesNotExist, ValueError):
        return JsonResponse({"items": [], "error": "Bill not found"})

    if not bill:
        return JsonResponse({"items": [], "error": "Bill not found"})

    if not request.user.is_superuser and bill.branch != request.user.active_branch:
        return JsonResponse({"items": [], "error": "This invoice does not belong to your active branch."})

    items, _ = _get_bill_items_data(bill)

    return JsonResponse({
        "items": items,
        "products": [],
        "branch_id": bill.branch.id if bill else ""
    })


@login_required
@never_cache
def get_replacement_product_api(request):
    """AJAX endpoint: returns product details by barcode and branch ID for exchange replacement lookup."""
    from core.models import Branch, ProductRegistry
    barcode = request.GET.get('barcode', '').strip()
    branch_id = request.GET.get('branch_id', '')

    if not barcode:
        return JsonResponse({'error': 'No barcode provided'}, status=400)
    if not branch_id:
        return JsonResponse({'error': 'No branch ID provided'}, status=400)

    try:
        from django.shortcuts import get_object_or_404
        branch = get_object_or_404(Branch, id=branch_id)
        if branch not in request.user.get_accessible_branches():
            return JsonResponse({'error': 'Permission denied'}, status=403)

        registry = ProductRegistry.objects.select_related('product').get(
            product__barcode=barcode,
            branch=branch
        )
        return JsonResponse({
            'id': registry.product.id,
            'name': registry.product.name,
            'barcode': registry.product.barcode,
            'price': float(registry.product.price),
            'stock': registry.stock_quantity
        })
    except ProductRegistry.DoesNotExist:
        return JsonResponse({'error': 'Product not found at this branch'}, status=404)


def _process_stock(ret, user):
    """Process stock changes based on return condition and action type.

    GOOD condition  → Add back to stock (IN transaction)
    DAMAGED condition → Record damage adjustment (Op/In/Out/Cl)
    """
    product = ret.product
    branch = ret.active_branch
    qty = ret.quantity

    if not product or not branch:
        return

    registry, _ = ProductRegistry.objects.get_or_create(
        product=product,
        branch=branch,
        defaults={"stock_quantity": 0},
    )

    if ret.condition == "GOOD":
        if ret.action_type in ("EXCHANGE", "EXCH_SAME"):
            # Net‑neutral exchange: no stock change
            pass
        else:
            # Treat as refund / other GOOD actions
            registry.stock_quantity += qty
            registry.save()
            StockTransaction.objects.create(
                product=product,
                branch=branch,
                transaction_type="IN",
                quantity=qty,
                reference=f"Return #{ret.pk} ({ret.get_action_type_display()})",
                user=user,
            )
    elif ret.condition == "DAMAGED":
        # Record a damage adjustment
        from django.db.models import Sum, Q
        txns = StockTransaction.objects.filter(product=product, branch=branch)
        stock_in = txns.filter(transaction_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
        stock_out = txns.filter(transaction_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0
        opening = registry.stock_quantity - stock_in + stock_out
        correction = -qty
        closing = registry.stock_quantity + correction
        StockAdjustment.objects.create(
            product=product,
            branch=branch,
            opening_balance=opening,
            closing_balance=closing,
            adjustment_quantity=correction,
            reference=f"Return #{ret.pk} damaged",
            user=user,
        )
