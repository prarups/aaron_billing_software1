from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .forms import ReturnCreateForm
from .models import Bill, BillItem
from core.models import ProductRegistry, StockTransaction, StockAdjustment


@login_required
def return_create_view(request):
    from .return_models import ReturnRequest
    from django.db.models import Sum

    if request.method == 'POST':
        form = ReturnCreateForm(request.POST)
        if form.is_valid():
            returns = form.save(request.user)
            messages.success(request, f"Processed {len(returns)} returned item(s).")
            return redirect('stock_pivot_report')
    else:
        initial = {}
        invoice_id = request.GET.get('invoice_id')
        if invoice_id:
            try:
                invoice_id_str = str(invoice_id).strip()
                bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
                if not bill:
                    if invoice_id_str.isdigit():
                        bill = Bill.objects.get(id=int(invoice_id_str))
                    else:
                        raise Bill.DoesNotExist()
                initial['invoice_id'] = bill.invoice_number or str(bill.id)
            except Bill.DoesNotExist:
                initial['invoice_id'] = invoice_id
        form = ReturnCreateForm(initial=initial)

    # Pass bill items for JS product dropdown (if invoice_id is given)
    import json
    bill_items_json = '[]'
    invoice_id = request.GET.get('invoice_id') or request.POST.get('invoice_id')
    if invoice_id:
        try:
            invoice_id_str = str(invoice_id).strip()
            bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
            if not bill:
                if invoice_id_str.isdigit():
                    bill = Bill.objects.get(id=int(invoice_id_str))
                else:
                    raise Bill.DoesNotExist()

            bill_items = []
            for item in bill.items.select_related('product').all():
                returned_qty = ReturnRequest.objects.filter(
                    bill_item=item,
                    status=ReturnRequest.Status.APPROVED
                ).aggregate(total=Sum('quantity'))['total'] or 0
                remaining_qty = max(0, item.quantity - returned_qty)
                bill_items.append({
                    'id': item.id,
                    'product_name': item.product.name,
                    'product_barcode': item.product.barcode,
                    'quantity': item.quantity,
                    'returned_quantity': returned_qty,
                    'remaining_quantity': remaining_qty,
                    'unit_price': int(item.unit_price),
                })
            bill_items_json = json.dumps(bill_items)
        except (Bill.DoesNotExist, ValueError):
            pass

    return render(request, 'billing/return_form.html', {
        'form': form,
        'bill_items_json': bill_items_json,
    })


@login_required
def get_bill_items_api(request):
    """AJAX endpoint: returns bill items for a given invoice ID including return history details."""
    from .return_models import ReturnRequest
    from django.db.models import Sum

    invoice_id = request.GET.get('invoice_id')
    print(f"DEBUG get_bill_items_api: Received invoice_id={repr(invoice_id)}")
    if not invoice_id:
        return JsonResponse({'items': []})
    try:
        invoice_id_str = str(invoice_id).strip()
        print(f"DEBUG get_bill_items_api: Stripped invoice_id_str={repr(invoice_id_str)}")
        bill = Bill.objects.filter(invoice_number__iexact=invoice_id_str).first()
        print(f"DEBUG get_bill_items_api: Lookup by invoice_number={repr(bill)}")
        if not bill:
            if invoice_id_str.isdigit():
                bill = Bill.objects.get(id=int(invoice_id_str))
                print(f"DEBUG get_bill_items_api: Lookup by id={repr(bill)}")
            else:
                print(f"DEBUG get_bill_items_api: Raising DoesNotExist")
                raise Bill.DoesNotExist()
    except (Bill.DoesNotExist, ValueError) as e:
        print(f"DEBUG get_bill_items_api: Error caught: {e}")
        return JsonResponse({'items': [], 'error': 'Bill not found'})

    items = []
    for item in bill.items.select_related('product').all():
        returned_qty = ReturnRequest.objects.filter(
            bill_item=item,
            status=ReturnRequest.Status.APPROVED
        ).aggregate(total=Sum('quantity'))['total'] or 0
        remaining_qty = max(0, item.quantity - returned_qty)
        items.append({
            'id': item.id,
            'product_name': item.product.name,
            'product_barcode': item.product.barcode,
            'quantity': item.quantity,
            'returned_quantity': returned_qty,
            'remaining_quantity': remaining_qty,
            'unit_price': int(item.unit_price),
        })
    return JsonResponse({'items': items})


def _process_stock(ret, user):
    """
    Process stock changes based on return condition and action type.

    GOOD condition  → Add back to stock (IN transaction)
    DAMAGED condition → Record damage adjustment (Op/In/Out/Cl)
    """
    product = ret.product
    branch = ret.active_branch
    qty = ret.quantity

    if not product or not branch:
        return

    # Get or create product registry for this branch
    registry, _ = ProductRegistry.objects.get_or_create(
        product=product,
        branch=branch,
        defaults={'stock_quantity': 0}
    )

    if ret.condition == 'GOOD':
        # ── GOOD CONDITION handling ──
        if ret.action_type == 'EXCHANGE':
            # Net‑neutral exchange: do not modify stock_quantity or create ledger entries.
            # The returned good replaces the sold good, leaving stock unchanged.
            pass
        elif ret.action_type == 'REFUND':
            # REFUND: increase stock and record IN transaction (no OUT change)
            registry.stock_quantity += qty
            registry.save()
            # Cleanup any OUT transaction related to this return (covers any reference format)
            StockTransaction.objects.filter(
                product=product,
                branch=branch,
                transaction_type='OUT',
                reference__contains=f'Return #{ret.pk}'
            ).delete()
            # Record IN transaction for refund
            StockTransaction.objects.create(
                product=product,
                branch=branch,
                transaction_type='IN',
                quantity=qty,
                reference=f'Return #{ret.pk} ({ret.get_action_type_display()})',
                user=user,
            )
        else:
            # Other GOOD actions (if any): treat as refund
            registry.stock_quantity += qty
            registry.save()
            StockTransaction.objects.create(
                product=product,
                branch=branch,
                transaction_type='IN',
                quantity=qty,
                reference=f'Return #{ret.pk} ({ret.get_action_type_display()})',
                user=user,
            )

    elif ret.condition == 'DAMAGED':
        # ── DAMAGED: Record a damage adjustment (Op / In / Out / Cl) ──
        # We do NOT add damaged goods back to sellable stock.
        # Instead we record a StockAdjustment for audit trail.

        # Calculate current stock summary for snapshot
        from django.db.models import Sum, Q
        txns = StockTransaction.objects.filter(product=product, branch=branch)
        stock_in = txns.filter(transaction_type='IN').aggregate(t=Sum('quantity'))['t'] or 0
        stock_out = txns.filter(transaction_type='OUT').aggregate(t=Sum('quantity'))['t'] or 0

        # Opening balance = first stock qty before any transactions
        # For simplicity: Op = current stock - In + Out
        opening = registry.stock_quantity - stock_in + stock_out

        # Damaged goods are recorded as negative adjustment
        correction = -qty
        closing = registry.stock_quantity + correction

        StockAdjustment.objects.create(
            product=product,
            branch=branch,
            opening_balance=opening,
            stock_in=stock_in,
            stock_out=stock_out,
            correction_amount=correction,
            closing_stock=closing,
            is_in_stock=(closing > 0),
            reason=f'Damaged return #{ret.pk} – {ret.reason}',
            user=user,
        )

        # Create DMG transaction
        StockTransaction.objects.create(
            product=product,
            branch=branch,
            transaction_type='DMG',
            quantity=qty,
            reference=f'Damaged Return #{ret.pk}',
            user=user,
        )

        # Update registry stock (damaged goods reduce stock)
        registry.stock_quantity = closing
        registry.save()
