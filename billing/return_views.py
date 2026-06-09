from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .forms import ReturnCreateForm
from .models import Bill, BillItem
from core.models import ProductRegistry, StockTransaction, StockAdjustment

@login_required
def return_create_view(request):
    """Handle product return creation.
    GET: display form with optional pre‑filled invoice ID and bill items.
    POST: validate form, process returns, and redirect on success.
    """
    from .return_models import ReturnRequest
    from django.db.models import Sum

    # ---------- POST handling ----------
    if request.method == "POST":
        form = ReturnCreateForm(request.POST)
        if form.is_valid():
            returns = form.save(request.user)
            messages.success(request, f"Processed {len(returns)} returned item(s).")
            return redirect("stock_pivot_report")
        else:
            print(f"DEBUG return_create_view form errors: {form.errors.as_data()}")
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
                if bill:
                    initial["invoice_id"] = bill.invoice_number or str(bill.id)
                else:
                    initial["invoice_id"] = invoice_id
            except Bill.DoesNotExist:
                initial["invoice_id"] = invoice_id
        form = ReturnCreateForm(initial=initial)

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
            bill_items = []
            for item in bill.items.select_related("product").all():
                returned_qty = ReturnRequest.objects.filter(
                    bill_item=item,
                    status=ReturnRequest.Status.APPROVED,
                ).aggregate(total=Sum("quantity"))['total'] or 0
                remaining_qty = max(0, item.quantity - returned_qty)
                bill_items.append({
                    "id": item.id,
                    "product_name": item.product.name,
                    "product_barcode": item.product.barcode,
                    "quantity": item.quantity,
                    "returned_quantity": returned_qty,
                    "remaining_quantity": remaining_qty,
                    "unit_price": int(item.unit_price),
                })
            bill_items_json = json.dumps(bill_items)
        except (Bill.DoesNotExist, ValueError):
            pass

    selected_bill_item = form.data.get("bill_item") if form.is_bound else ""
    selected_quantity = form.data.get("quantity") if form.is_bound else 1
    selected_condition = form.data.get("condition") if form.is_bound else "GOOD"
    selected_action_type = form.data.get("action_type") if form.is_bound else "EXCH_SAME"

    return render(request, "billing/return_form.html", {
        "form": form,
        "bill_items_json": bill_items_json,
        "selected_bill_item": selected_bill_item,
        "selected_quantity": selected_quantity,
        "selected_condition": selected_condition,
        "selected_action_type": selected_action_type,
    })


@login_required
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

    items = []
    for item in bill.items.select_related("product").all():
        returned_qty = ReturnRequest.objects.filter(
            bill_item=item,
            status=ReturnRequest.Status.APPROVED,
        ).aggregate(total=Sum("quantity"))['total'] or 0
        remaining_qty = max(0, item.quantity - returned_qty)
        items.append({
            "id": item.id,
            "product_name": item.product.name,
            "product_barcode": item.product.barcode,
            "quantity": item.quantity,
            "returned_quantity": returned_qty,
            "remaining_quantity": remaining_qty,
            "unit_price": int(item.unit_price),
        })
    return JsonResponse({"items": items})


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
