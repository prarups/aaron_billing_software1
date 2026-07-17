from django import forms
from django.utils import timezone
from .return_models import ReturnRequest, CreditNote
from .models import Bill, BillItem

class ReturnCreateForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    invoice_id = forms.CharField(
        label='Invoice / Bill ID',
        widget=forms.TextInput(attrs={
            'class': 'form-control rounded-pill border-0 bg-light',
            'placeholder': 'Enter Bill # (e.g. AN-0001)',
        })
    )
    bill_item = forms.IntegerField(
        label='Select Product to Return',
        widget=forms.Select(attrs={
            'class': 'form-select rounded-pill border-0 bg-light',
        }),
        required=False,
    )
    quantity = forms.IntegerField(
        label='Return Quantity',
        min_value=1,
        initial=1,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-pill border-0 bg-light',
            'min': '1',
            'step': '1',
        })
    )
    condition = forms.ChoiceField(
        label='Product Condition',
        choices=ReturnRequest.CONDITION_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select rounded-pill border-0 bg-light',
            'data-no-search': 'true',
        })
    )
    action_type = forms.ChoiceField(
        label='Return Action',
        choices=[
            ('EXCHANGE', 'Exchange Product')
        ],
        initial='EXCHANGE',
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select rounded-pill border-0 bg-light',
            'data-no-search': 'true',
        })
    )
    reason = forms.CharField(
        label='Reason for Return',
        widget=forms.Textarea(attrs={
            'class': 'form-control border-0 bg-light',
            'rows': 3,
            'placeholder': 'Why is this product being returned?',
            'style': 'border-radius: 1rem;',
        }),
        required=True,
    )
    return_items = forms.CharField(
        widget=forms.HiddenInput(attrs={
            'id': 'id_return_items',
        }),
        required=False,
    )
    payment_method = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={
            'id': 'id_payment_method',
        }),
        initial='cash'
    )
    cash_amount = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(attrs={
            'id': 'id_cash_amount',
        }),
        initial=0.00
    )
    online_amount = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(attrs={
            'id': 'id_online_amount',
        }),
        initial=0.00
    )

    def clean_invoice_id(self):
        invoice_val = self.cleaned_data['invoice_id'].strip()
        try:
            # First try lookup by invoice_number
            bill = Bill.objects.filter(invoice_number__iexact=invoice_val).first()
            if not bill:
                # If not found, try lookup by database ID if it is an integer
                if invoice_val.isdigit():
                    bill = Bill.objects.get(id=int(invoice_val))
                else:
                    raise Bill.DoesNotExist()
            
            if self.user and not self.user.is_superuser and bill.branch != self.user.active_branch:
                raise forms.ValidationError('This invoice does not belong to your active branch.')
        except (Bill.DoesNotExist, ValueError):
            raise forms.ValidationError('Invoice not found.')
        return bill

    def clean_bill_item(self):
        bill_item_id = self.cleaned_data.get('bill_item')
        if not bill_item_id:
            return None
        try:
            item = BillItem.objects.select_related('product').get(id=bill_item_id)
        except BillItem.DoesNotExist:
            raise forms.ValidationError('Selected product item not found.')
        return item

    def clean(self):
        cleaned = super().clean()
        bill = cleaned.get('invoice_id')
        return_items_json = cleaned.get('return_items', '[]') or '[]'

        if not bill:
            return cleaned

        import json
        try:
            return_items = json.loads(return_items_json)
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid return items data format.')

        # If return list is empty, but they filled the standard dropdown, we can fall back to the dropdown item.
        if not return_items:
            item = cleaned.get('bill_item')
            qty = cleaned.get('quantity', 1)
            # For fallback, we need a replacement. If none is in dropdown, we raise error.
            raise forms.ValidationError('Please add at least one product to the return list.')

        # Validate each item in the return list
        validated_items = []
        from core.models import Product, ComboGroup, ProductRegistry
        simulated_stock = {}
        item_qty_tracker = {}
        total_returned_value = 0
        total_replacement_value = 0

        # Pre-cache combo information for the bill to avoid N+1 queries in the loop
        bill_combos = ComboGroup.objects.filter(
            branches=bill.branch,
            is_active=True
        ).prefetch_related('products', 'tiers')
        
        bill_items_cache = list(bill.items.select_related('product').all())
        bill_item_quantities = {item.product_id: item.quantity for item in bill_items_cache}
        
        combo_map = {} # item.id -> bool
        combo_group_map = {} # item.id -> ComboGroup
        
        for cg in bill_combos:
            cg_product_ids = {p.id for p in cg.products.all()}
            min_qty = min((t.quantity for t in cg.tiers.all()), default=1)
            total_group_qty = sum(qty for pid, qty in bill_item_quantities.items() if pid in cg_product_ids)
            
            for item in bill_items_cache:
                if item.product_id in cg_product_ids:
                    combo_group_map[item.id] = cg
                    if total_group_qty >= min_qty:
                        combo_map[item.id] = True

        for ri in return_items:
            try:
                # Support nullable item ID for replacement-only items
                item_id_raw = ri.get('id')
                if item_id_raw is not None and str(item_id_raw).isdigit():
                    item_id = int(item_id_raw)
                else:
                    item_id = None
                
                qty = int(ri['quantity'])
                rep_prod_id = int(ri['replacement_product_id'])
                rep_qty = int(ri.get('replacement_quantity', qty))
            except (ValueError, KeyError, TypeError):
                raise forms.ValidationError('Invalid product, quantity, or replacement product in return list.')

            if item_id is not None:
                if qty < 1:
                    raise forms.ValidationError('Return quantity must be at least 1.')

                # Fetch from cache instead of DB to save queries
                item = next((i for i in bill_items_cache if i.id == item_id), None)
                if not item:
                    raise forms.ValidationError('Product item not found.')

                if item.bill_id != bill.id:
                    raise forms.ValidationError(f'Product {item.product.name} does not belong to this bill.')

                # Track cumulative quantity for this item across multiple entries in the same return
                current_qty = item_qty_tracker.get(item_id, 0) + qty
                item_qty_tracker[item_id] = current_qty

                # Check remaining returnable quantity
                from .return_models import ReturnRequest
                from django.db.models import Sum
                returned_qty = ReturnRequest.objects.filter(
                    bill_item=item,
                    status=ReturnRequest.Status.APPROVED
                ).aggregate(total=Sum('quantity'))['total'] or 0

                remaining_qty = max(0, item.quantity - returned_qty)
                if current_qty > remaining_qty:
                    raise forms.ValidationError(
                        f'Total return quantity ({current_qty}) for {item.product.name} exceeds remaining returnable quantity ({remaining_qty}).'
                    )
            else:
                item = None
                qty = 0

            try:
                rep_product = Product.objects.get(id=rep_prod_id)
            except Product.DoesNotExist:
                raise forms.ValidationError('Replacement product not found.')

            # Check replacement product stock availability at bill's branch
            if rep_product.id not in simulated_stock:
                try:
                    rep_registry = ProductRegistry.objects.get(product=rep_product, branch=bill.branch)
                    simulated_stock[rep_product.id] = rep_registry.stock_quantity
                except ProductRegistry.DoesNotExist:
                    # Fallback to barcode lookup if the branch has a duplicate product instance
                    try:
                        rep_registry = ProductRegistry.objects.get(product__barcode=rep_product.barcode, branch=bill.branch)
                        simulated_stock[rep_product.id] = rep_registry.stock_quantity
                    except ProductRegistry.DoesNotExist:
                        simulated_stock[rep_product.id] = 0

            cond = ri.get('condition', 'GOOD')
            # Ensure there is sufficient stock already available on the shelf
            # (excluding the returned item itself) so a replacement can actually be provided.
            if simulated_stock[rep_product.id] < rep_qty:
                raise forms.ValidationError(
                    f'Insufficient stock for replacement product "{rep_product.name}" at this branch. '
                    f'Available stock: {simulated_stock[rep_product.id]}, requested: {rep_qty}.'
                )

            # Deduct replacement from simulated stock
            simulated_stock[rep_product.id] -= rep_qty

            # Validate Combo Group constraints vs Normal constraints:
            # We now allow exchanging a combo item for a non-combo product.
            # `is_combo` (balanced combo swap) only applies if the replacement product
            # is inside the returned item's combo group.
            is_combo = False
            if item and combo_map.get(item.id, False):
                combo_group = combo_group_map.get(item.id)
                if combo_group:
                    cg_product_ids = {p.id for p in combo_group.products.all()}
                    if rep_product.id in cg_product_ids:
                        is_combo = True

            if is_combo:
                # Balanced combo swap: add replacement price to both totals so they cancel out
                total_returned_value += rep_product.price * rep_qty
                total_replacement_value += rep_product.price * rep_qty
            else:
                if item:
                    total_returned_value += item.unit_price * qty
                total_replacement_value += rep_product.price * rep_qty

            validated_items.append({
                'bill_item': item,
                'quantity': qty,
                'condition': cond,
                'action_type': 'EXCHANGE',
                'replacement_product': rep_product,
                'replacement_quantity': rep_qty,
            })

        total_difference = total_replacement_value - total_returned_value
        if total_difference > 0:
            payment_method = cleaned.get('payment_method', 'cash') or 'cash'
            cash_amount = cleaned.get('cash_amount', 0) or 0
            online_amount = cleaned.get('online_amount', 0) or 0

            if payment_method not in ('cash', 'online', 'split'):
                raise forms.ValidationError('Invalid payment method selected for difference.')

            if payment_method == 'split':
                if abs((cash_amount + online_amount) - total_difference) > 0.01:
                    raise forms.ValidationError(
                        f'For split payment, the sum of cash (₹{cash_amount:.0f}) and online (₹{online_amount:.0f}) must equal the total difference of ₹{total_difference:.0f}.'
                    )
            elif payment_method == 'cash':
                cleaned['cash_amount'] = total_difference
                cleaned['online_amount'] = 0
            elif payment_method == 'online':
                cleaned['online_amount'] = total_difference
                cleaned['cash_amount'] = 0
        else:
            cleaned['payment_method'] = 'cash'
            cleaned['cash_amount'] = 0
            cleaned['online_amount'] = 0

        cleaned['validated_return_items'] = validated_items
        return cleaned

    def save(self, user):
        bill = self.cleaned_data['invoice_id']
        reason = self.cleaned_data['reason']
        validated_items = self.cleaned_data['validated_return_items']

        # Pre-calculate positive difference totals for payment allocation
        from core.models import ComboGroup
        total_positive_difference = 0
        positive_diff_items_count = 0
        for vi in validated_items:
            item = vi['bill_item']
            qty = vi['quantity']
            rep_product = vi['replacement_product']
            rep_qty = vi['replacement_quantity']
            
            is_combo = False
            if item and item.is_combo_purchase:
                is_combo = ComboGroup.objects.filter(
                    products=item.product,
                    branches=bill.branch,
                    is_active=True
                ).filter(products=rep_product).exists()

            if not is_combo:
                unit_price = item.unit_price if item else 0
                price_diff = (rep_product.price * rep_qty) - (unit_price * qty)
                if price_diff > 0:
                    total_positive_difference += price_diff
                    positive_diff_items_count += 1

        payment_method = self.cleaned_data.get('payment_method', 'cash') or 'cash'
        total_cash_amount = float(self.cleaned_data.get('cash_amount', 0) or 0)
        total_online_amount = float(self.cleaned_data.get('online_amount', 0) or 0)

        assigned_cash = 0.0
        assigned_online = 0.0
        positive_diff_processed = 0

        from core.models import ProductRegistry, StockTransaction
        returns = []
        for vi in validated_items:
            item = vi['bill_item']
            qty = vi['quantity']
            condition = vi['condition']
            action_type = vi['action_type']
            rep_product = vi['replacement_product']
            rep_qty = vi['replacement_quantity']

            # Check if combo product to determine price difference
            is_combo = False
            if item and item.is_combo_purchase:
                is_combo = ComboGroup.objects.filter(
                    products=item.product,
                    branches=bill.branch,
                    is_active=True
                ).filter(products=rep_product).exists()

            if is_combo:
                price_diff = 0
            else:
                unit_price = item.unit_price if item else 0
                price_diff = (rep_product.price * rep_qty) - (unit_price * qty)

            # Apportion cash and online amounts
            if price_diff > 0 and total_positive_difference > 0:
                positive_diff_processed += 1
                if positive_diff_processed == positive_diff_items_count:
                    req_cash = total_cash_amount - assigned_cash
                    req_online = total_online_amount - assigned_online
                else:
                    proportion = float(price_diff) / float(total_positive_difference)
                    req_cash = round(total_cash_amount * proportion, 2)
                    req_online = round(total_online_amount * proportion, 2)
                    assigned_cash += req_cash
                    assigned_online += req_online
            else:
                req_cash = 0.00
                req_online = 0.00

            # Create approved ReturnRequest
            ret = ReturnRequest.objects.create(
                invoice=bill,
                bill_item=item,
                product=item.product if item else None,
                quantity=qty,
                condition=condition,
                action_type=action_type,
                replacement_product=rep_product,
                replacement_quantity=rep_qty,
                price_difference=price_diff,
                payment_method=payment_method,
                cash_amount=req_cash,
                online_amount=req_online,
                requested_by=user,
                product_name=item.product.name if item else f"Replacement: {rep_product.name}",
                reason=reason,
                status=ReturnRequest.Status.APPROVED,
                active_branch=user.active_branch,
            )

            # Update cache/helper fields on Bill and BillItem
            if item:
                item.returned_quantity += qty
                item.save()

            bill.has_returns = True
            bill.save()

            # Process stock updates directly here in a single transaction context
            # 1. Update returned product stock
            if item:
                try:
                    ret_registry = ProductRegistry.objects.get(product=item.product, branch=bill.branch)
                except ProductRegistry.DoesNotExist:
                    try:
                        ret_registry = ProductRegistry.objects.get(product__barcode=item.product.barcode, branch=bill.branch)
                    except ProductRegistry.DoesNotExist:
                        ret_registry = ProductRegistry.objects.create(
                            product=item.product,
                            branch=bill.branch,
                            stock_quantity=0,
                            damaged_qty=0
                        )

                if condition == 'GOOD':
                    ret_registry.stock_quantity += qty
                    ret_registry.save()
                    StockTransaction.objects.create(
                        product=ret_registry.product,
                        branch=bill.branch,
                        transaction_type='IN',
                        quantity=qty,
                        reference=f"Return #{ret.pk} (GOOD)",
                        user=user
                    )
                elif condition == 'DAMAGED':
                    ret_registry.damaged_qty += qty
                    ret_registry.save()
                    StockTransaction.objects.create(
                        product=ret_registry.product,
                        branch=bill.branch,
                        transaction_type='DMG',
                        quantity=qty,
                        reference=f"Return #{ret.pk} (DAMAGED)",
                        user=user
                    )

            # 2. Update replacement product stock
            if rep_product:
                try:
                    rep_registry = ProductRegistry.objects.get(product=rep_product, branch=bill.branch)
                except ProductRegistry.DoesNotExist:
                    try:
                        rep_registry = ProductRegistry.objects.get(product__barcode=rep_product.barcode, branch=bill.branch)
                    except ProductRegistry.DoesNotExist:
                        rep_registry = ProductRegistry.objects.create(
                            product=rep_product,
                            branch=bill.branch,
                            stock_quantity=0,
                            damaged_qty=0
                        )

                rep_registry.stock_quantity -= rep_qty
                rep_registry.save()
                StockTransaction.objects.create(
                    product=rep_registry.product,
                    branch=bill.branch,
                    transaction_type='OUT',
                    quantity=rep_qty,
                    reference=f"Exchange Swap for Return #{ret.pk}",
                    user=user
                )

            returns.append(ret)

        # After processing all items, if the net difference is negative, create a CreditNote
        from decimal import Decimal
        total_returned_value = Decimal('0')
        total_replacement_value = Decimal('0')
        for vi in validated_items:
            item = vi['bill_item']
            qty = vi['quantity']
            rep_product = vi['replacement_product']
            rep_qty = vi['replacement_quantity']
            
            is_combo = False
            if item and item.is_combo_purchase:
                from core.models import ComboGroup
                is_combo = ComboGroup.objects.filter(
                    products=item.product,
                    branches=bill.branch,
                    is_active=True
                ).filter(products=rep_product).exists()

            if is_combo:
                total_returned_value += Decimal(str(rep_product.price)) * rep_qty
                total_replacement_value += Decimal(str(rep_product.price)) * rep_qty
            else:
                if item:
                    total_returned_value += Decimal(str(item.unit_price)) * qty
                total_replacement_value += Decimal(str(rep_product.price)) * rep_qty

        total_difference = total_replacement_value - total_returned_value
        if total_difference < 0:
            from .return_models import CreditNote
            CreditNote.objects.create(
                invoice=bill,
                amount=abs(total_difference),
                reason=reason or f"Return/Exchange refund difference",
                issued_by=user
            )

        return returns
