import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, models
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
import datetime

from core.models import Branch, Product, ProductRegistry, StockTransaction
from .models import StockTransfer, StockTransferItem


def generate_transfer_number():
    import re
    max_num = 1000
    for st in StockTransfer.objects.all():
        match = re.search(r'\d+', st.transfer_number)
        if match:
            num = int(match.group())
            if num > max_num:
                max_num = num
    next_num = max_num + 1
    candidate = f"TR-{next_num}"
    while StockTransfer.objects.filter(transfer_number=candidate).exists():
        next_num += 1
        candidate = f"TR-{next_num}"
    return candidate


def is_admin_user(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    user_role = getattr(user, 'role', '')
    return user_role in ['owner', 'admin', 'general_manager', 'manager', 'regional_manager']


@login_required
def stock_transfer_list(request):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied: Stock Transfer privileges are restricted to Admin users.")
        return redirect('portal_choice')

    transfers = StockTransfer.objects.select_related('from_branch', 'to_branch', 'created_by').prefetch_related('items__product').all()

    # Filtering
    from_branch_id = request.GET.get('from_branch')
    to_branch_id = request.GET.get('to_branch')
    status = request.GET.get('status')
    search_query = request.GET.get('q', '').strip()

    if from_branch_id:
        transfers = transfers.filter(from_branch_id=from_branch_id)
    if to_branch_id:
        transfers = transfers.filter(to_branch_id=to_branch_id)
    if status:
        transfers = transfers.filter(status=status)
    if search_query:
        transfers = transfers.filter(
            models.Q(from_branch__code__icontains=search_query) |
            models.Q(from_branch__name__icontains=search_query) |
            models.Q(to_branch__code__icontains=search_query) |
            models.Q(to_branch__name__icontains=search_query) |
            models.Q(transfer_number__icontains=search_query) |
            models.Q(items__product__barcode__icontains=search_query) |
            models.Q(items__product__name__icontains=search_query)
        ).distinct()

    total_transfers = transfers.count()
    completed_transfers = transfers.filter(status='COMPLETED').count()
    total_items = sum(t.total_items for t in transfers if t.status == 'COMPLETED')

    branches = Branch.objects.all()

    context = {
        'transfers': transfers,
        'branches': branches,
        'total_transfers': total_transfers,
        'completed_transfers': completed_transfers,
        'total_items': total_items,
        'selected_from': from_branch_id,
        'selected_to': to_branch_id,
        'selected_status': status,
        'search_query': search_query,
    }
    return render(request, 'inventory/stock_transfer_list.html', context)


@login_required
def stock_transfer_create(request):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied: Stock Transfer privileges are restricted to Admin users.")
        return redirect('portal_choice')

    branches = Branch.objects.all()

    if request.method == 'POST':
        transfer_method = request.POST.get('transfer_method', 'manual')
        from_branch_id = request.POST.get('from_branch')
        to_branch_id = request.POST.get('to_branch')
        notes = request.POST.get('notes', '').strip()

        if not from_branch_id or not to_branch_id:
            messages.error(request, "Please select both Source and Destination branches.")
            return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

        if from_branch_id == to_branch_id:
            messages.error(request, "Source and Destination branches cannot be the same!")
            return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

        from_branch = get_object_or_404(Branch, pk=from_branch_id)
        to_branch = get_object_or_404(Branch, pk=to_branch_id)

        # Excel Upload Handling
        if transfer_method == 'excel':
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "Please choose an Excel file (.xlsx) to upload.")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            try:
                wb = openpyxl.load_workbook(excel_file, data_only=True)
                sheet = wb.active
            except Exception as e:
                messages.error(request, f"Error reading Excel file: {str(e)}")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            # Read rows
            items_to_transfer = []
            errors = []
            
            # Row 1 is header: Barcode, Quantity, [Name], [Notes]
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not row or not any(row):
                    continue
                
                barcode = str(row[0]).strip() if row[0] is not None else ''
                if not barcode:
                    continue

                try:
                    qty = int(row[1]) if len(row) > 1 and row[1] is not None else 0
                except (ValueError, TypeError):
                    errors.append(f"Row {row_idx}: Invalid quantity '{row[1]}' for barcode '{barcode}'.")
                    continue

                if qty <= 0:
                    errors.append(f"Row {row_idx}: Quantity must be greater than 0 for barcode '{barcode}'.")
                    continue

                # Product Lookup
                try:
                    product = Product.objects.get(barcode=barcode)
                except Product.DoesNotExist:
                    errors.append(f"Row {row_idx}: Product with barcode '{barcode}' not found in database.")
                    continue

                # Check Source Stock
                reg = ProductRegistry.objects.filter(branch=from_branch, product=product).first()
                available_stock = reg.stock_quantity if reg else 0
                if available_stock < qty:
                    errors.append(f"Row {row_idx}: '{product.name}' ({barcode}) has only {available_stock} units available in {from_branch.name}, but requested {qty}.")
                    continue

                items_to_transfer.append({
                    'product': product,
                    'quantity': qty,
                    'notes': str(row[3]).strip() if len(row) > 3 and row[3] is not None else ''
                })

            if errors:
                for err in errors[:10]: # Show top 10 errors
                    messages.error(request, err)
                if len(errors) > 10:
                    messages.error(request, f"... and {len(errors) - 10} more errors. Please fix Excel file.")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            if not items_to_transfer:
                messages.error(request, "No valid transfer items found in the Excel file.")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            # Perform Atomic Stock Transfer
            with transaction.atomic():
                transfer_number = generate_transfer_number()

                transfer = StockTransfer.objects.create(
                    transfer_number=transfer_number,
                    from_branch=from_branch,
                    to_branch=to_branch,
                    created_by=request.user,
                    status='COMPLETED',
                    notes=notes or f"Excel Bulk Transfer ({len(items_to_transfer)} items)"
                )

                for item in items_to_transfer:
                    prod = item['product']
                    qty = item['quantity']
                    item_note = item['notes']

                    StockTransferItem.objects.create(
                        transfer=transfer,
                        product=prod,
                        quantity=qty,
                        notes=item_note
                    )

                    # Deduct from Source Branch
                    src_reg, _ = ProductRegistry.objects.get_or_create(branch=from_branch, product=prod)
                    src_reg.stock_quantity -= qty
                    src_reg.save()

                    StockTransaction.objects.create(
                        product=prod,
                        branch=from_branch,
                        transaction_type='TR_OUT',
                        quantity=qty,
                        reference=f"Transfer #{transfer.transfer_number} to {to_branch.name}",
                        user=request.user
                    )

                    # Add to Destination Branch
                    dst_reg, _ = ProductRegistry.objects.get_or_create(branch=to_branch, product=prod)
                    dst_reg.stock_quantity += qty
                    dst_reg.save()

                    StockTransaction.objects.create(
                        product=prod,
                        branch=to_branch,
                        transaction_type='TR_IN',
                        quantity=qty,
                        reference=f"Transfer #{transfer.transfer_number} from {from_branch.name}",
                        user=request.user
                    )

            messages.success(request, f"Successfully transferred {len(items_to_transfer)} products from {from_branch.name} to {to_branch.name} via Excel Bulk Import!")
            return redirect('stock_transfer_list')

        # Manual Entry Handling
        else:
            product_ids = request.POST.getlist('product_id[]')
            quantities = request.POST.getlist('quantity[]')
            item_notes = request.POST.getlist('item_notes[]')

            if not product_ids:
                messages.error(request, "Please add at least one product row to transfer.")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            items_to_transfer = []
            errors = []

            for idx, (p_id, q_val) in enumerate(zip(product_ids, quantities), start=1):
                if not p_id:
                    continue
                try:
                    qty = int(q_val)
                except (ValueError, TypeError):
                    errors.append(f"Row {idx}: Invalid quantity entered.")
                    continue

                if qty <= 0:
                    errors.append(f"Row {idx}: Quantity must be at least 1.")
                    continue

                prod = Product.objects.filter(pk=p_id).first()
                if not prod:
                    errors.append(f"Row {idx}: Product not found.")
                    continue

                reg = ProductRegistry.objects.filter(branch=from_branch, product=prod).first()
                avail = reg.stock_quantity if reg else 0

                if avail < qty:
                    errors.append(f"Row {idx}: '{prod.name}' has only {avail} units available in {from_branch.name}, cannot transfer {qty}.")
                    continue

                i_note = item_notes[idx-1] if len(item_notes) >= idx else ''
                items_to_transfer.append({
                    'product': prod,
                    'quantity': qty,
                    'notes': i_note
                })

            if errors:
                for err in errors:
                    messages.error(request, err)
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            if not items_to_transfer:
                messages.error(request, "No valid items selected for transfer.")
                return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})

            with transaction.atomic():
                transfer_number = generate_transfer_number()

                transfer = StockTransfer.objects.create(
                    transfer_number=transfer_number,
                    from_branch=from_branch,
                    to_branch=to_branch,
                    created_by=request.user,
                    status='COMPLETED',
                    notes=notes or f"Manual Transfer ({len(items_to_transfer)} items)"
                )

                for item in items_to_transfer:
                    prod = item['product']
                    qty = item['quantity']
                    item_note = item['notes']

                    StockTransferItem.objects.create(
                        transfer=transfer,
                        product=prod,
                        quantity=qty,
                        notes=item_note
                    )

                    # Deduct Source
                    src_reg, _ = ProductRegistry.objects.get_or_create(branch=from_branch, product=prod)
                    src_reg.stock_quantity -= qty
                    src_reg.save()

                    StockTransaction.objects.create(
                        product=prod,
                        branch=from_branch,
                        transaction_type='TR_OUT',
                        quantity=qty,
                        reference=f"Transfer #{transfer.transfer_number} to {to_branch.name}",
                        user=request.user
                    )

                    # Add Destination
                    dst_reg, _ = ProductRegistry.objects.get_or_create(branch=to_branch, product=prod)
                    dst_reg.stock_quantity += qty
                    dst_reg.save()

                    StockTransaction.objects.create(
                        product=prod,
                        branch=to_branch,
                        transaction_type='TR_IN',
                        quantity=qty,
                        reference=f"Transfer #{transfer.transfer_number} from {from_branch.name}",
                        user=request.user
                    )

            messages.success(request, f"Successfully completed stock transfer #{transfer.transfer_number} ({len(items_to_transfer)} items)!")
            return redirect('stock_transfer_list')

    return render(request, 'inventory/stock_transfer_form.html', {'branches': branches})


@login_required
def download_transfer_template(request):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied.")
        return redirect('portal_choice')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Transfer Template"

    # Styling
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid") # Indigo theme
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    headers = ["Barcode", "Quantity", "Product Name (Optional)", "Notes (Optional)"]
    ws.append(headers)

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    # Sample rows
    sample_data = [
        ["10001", 10, "Men Cotton Shirt - Blue L", "Refill request for weekend sale"],
        ["8901234567", 25, "Women Denim Jeans - M", "Bulk stock transfer"],
        ["10005", 5, "Unisex Cap - Black", "Sample item"]
    ]

    for row_data in sample_data:
        ws.append(row_data)

    # Set column widths
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 35
    ws.column_dimensions['D'].width = 40

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response['Content-Disposition'] = 'attachment; filename="Stock_Transfer_Template.xlsx"'
    wb.save(response)
    return response


@login_required
def stock_transfer_detail(request, pk):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied.")
        return redirect('portal_choice')

    transfer = get_object_or_404(StockTransfer.objects.select_related('from_branch', 'to_branch', 'created_by').prefetch_related('items__product'), pk=pk)
    return render(request, 'inventory/stock_transfer_detail.html', {'transfer': transfer})


@login_required
def stock_transfer_edit(request, pk):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied.")
        return redirect('portal_choice')

    transfer = get_object_or_404(StockTransfer, pk=pk)

    if transfer.status == 'CANCELLED':
        messages.error(request, "Cannot edit a cancelled transfer.")
        return redirect('stock_transfer_list')

    if request.method == 'POST':
        notes = request.POST.get('notes', '').strip()
        item_ids = request.POST.getlist('item_id[]')
        new_quantities = request.POST.getlist('quantity[]')

        with transaction.atomic():
            for i_id, new_q in zip(item_ids, new_quantities):
                item = get_object_or_404(StockTransferItem, pk=i_id, transfer=transfer)
                old_qty = item.quantity
                try:
                    new_qty = int(new_q)
                except (ValueError, TypeError):
                    continue

                if new_qty <= 0 or new_qty == old_qty:
                    continue

                qty_diff = new_qty - old_qty

                # Adjust Source Branch Stock (- diff)
                src_reg, _ = ProductRegistry.objects.get_or_create(branch=transfer.from_branch, product=item.product)
                src_reg.stock_quantity -= qty_diff
                src_reg.save()

                # Adjust Destination Branch Stock (+ diff)
                dst_reg, _ = ProductRegistry.objects.get_or_create(branch=transfer.to_branch, product=item.product)
                dst_reg.stock_quantity += qty_diff
                dst_reg.save()

                # Log Adjustment Stock Transactions
                StockTransaction.objects.create(
                    product=item.product,
                    branch=transfer.from_branch,
                    transaction_type='ADJ',
                    quantity=-qty_diff,
                    reference=f"Edit Transfer #{transfer.transfer_number} (Qty: {old_qty} -> {new_qty})",
                    user=request.user
                )

                StockTransaction.objects.create(
                    product=item.product,
                    branch=transfer.to_branch,
                    transaction_type='ADJ',
                    quantity=qty_diff,
                    reference=f"Edit Transfer #{transfer.transfer_number} (Qty: {old_qty} -> {new_qty})",
                    user=request.user
                )

                # Update Item Qty
                item.quantity = new_qty
                item.save()

            transfer.notes = notes
            transfer.save()

        messages.success(request, f"Successfully updated Stock Transfer #{transfer.transfer_number}.")
        return redirect('stock_transfer_detail', pk=transfer.pk)

    return render(request, 'inventory/stock_transfer_edit.html', {'transfer': transfer})


@login_required
def stock_transfer_rollback(request, pk):
    if not is_admin_user(request.user):
        messages.error(request, "Access Denied.")
        return redirect('portal_choice')

    transfer = get_object_or_404(StockTransfer, pk=pk)

    if request.method == 'POST':
        if transfer.status == 'CANCELLED':
            messages.warning(request, "This transfer is already cancelled.")
            return redirect('stock_transfer_list')

        with transaction.atomic():
            # Revert all item quantities
            for item in transfer.items.all():
                qty = item.quantity
                prod = item.product

                # Restore to Source Branch
                src_reg, _ = ProductRegistry.objects.get_or_create(branch=transfer.from_branch, product=prod)
                src_reg.stock_quantity += qty
                src_reg.save()

                StockTransaction.objects.create(
                    product=prod,
                    branch=transfer.from_branch,
                    transaction_type='TR_IN',
                    quantity=qty,
                    reference=f"ROLLBACK Transfer #{transfer.transfer_number}",
                    user=request.user
                )

                # Revert from Destination Branch
                dst_reg, _ = ProductRegistry.objects.get_or_create(branch=transfer.to_branch, product=prod)
                dst_reg.stock_quantity -= qty
                dst_reg.save()

                StockTransaction.objects.create(
                    product=prod,
                    branch=transfer.to_branch,
                    transaction_type='TR_OUT',
                    quantity=qty,
                    reference=f"ROLLBACK Transfer #{transfer.transfer_number}",
                    user=request.user
                )

            transfer.status = 'CANCELLED'
            transfer.save()

        messages.success(request, f"Stock Transfer #{transfer.transfer_number} has been rolled back and cancelled successfully.")
        return redirect('stock_transfer_list')

    return redirect('stock_transfer_detail', pk=transfer.pk)


@login_required
def ajax_product_branch_stock(request):
    if not is_admin_user(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    branch_id = request.GET.get('branch_id')
    query = request.GET.get('query', '').strip()

    if not branch_id or not query:
        return JsonResponse({'products': []})

    registries = ProductRegistry.objects.filter(
        branch_id=branch_id
    ).filter(
        models.Q(product__name__icontains=query) | models.Q(product__barcode__icontains=query)
    ).select_related('product')[:15]

    results = []
    for reg in registries:
        results.append({
            'id': reg.product.id,
            'name': reg.product.name,
            'barcode': reg.product.barcode,
            'size': reg.product.size or '-',
            'price': str(reg.product.price),
            'stock_quantity': reg.stock_quantity
        })

    return JsonResponse({'products': results})
