from django import forms
from django.utils import timezone
from .return_models import ReturnRequest, CreditNote
from .models import Bill, BillItem

class ReturnCreateForm(forms.Form):
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
        from core.models import Product, ComboGroup
        for ri in return_items:
            try:
                item_id = int(ri['id'])
                qty = int(ri['quantity'])
                rep_prod_id = int(ri['replacement_product_id'])
                rep_qty = int(ri.get('replacement_quantity', qty))
            except (ValueError, KeyError, TypeError):
                raise forms.ValidationError('Invalid product, quantity, or replacement product in return list.')

            if qty < 1:
                raise forms.ValidationError('Return quantity must be at least 1.')

            try:
                item = BillItem.objects.select_related('product').get(id=item_id)
            except BillItem.DoesNotExist:
                raise forms.ValidationError('Product item not found.')

            if item.bill_id != bill.id:
                raise forms.ValidationError(f'Product {item.product.name} does not belong to this bill.')

            try:
                rep_product = Product.objects.get(id=rep_prod_id)
            except Product.DoesNotExist:
                raise forms.ValidationError('Replacement product not found.')

            # Check remaining returnable quantity
            from .return_models import ReturnRequest
            from django.db.models import Sum
            returned_qty = ReturnRequest.objects.filter(
                bill_item=item,
                status=ReturnRequest.Status.APPROVED
            ).aggregate(total=Sum('quantity'))['total'] or 0

            remaining_qty = max(0, item.quantity - returned_qty)
            if qty > remaining_qty:
                raise forms.ValidationError(
                    f'Return quantity ({qty}) for {item.product.name} exceeds remaining returnable quantity ({remaining_qty}).'
                )

            # Validate Combo Group constraints vs Normal constraints
            # Check if returned item was purchased as part of a combo
            if item.is_combo_purchase:
                combo_group = ComboGroup.objects.filter(
                    products=item.product,
                    branches=bill.branch,
                    is_active=True
                ).first()
                # Replacement must belong to the same combo group
                if not combo_group.products.filter(id=rep_product.id).exists():
                    raise forms.ValidationError(
                        f'Product {item.product.name} was sold as part of combo "{combo_group.name}". '
                        f'It can only be exchanged for products in the same combo group. '
                        f'{rep_product.name} is not in that combo group.'
                    )
            else:
                # Normal item exchange: replacement price must be >= returned unit price
                if rep_product.price < item.unit_price:
                    raise forms.ValidationError(
                        f'Product {item.product.name} is a normal item. '
                        f'Exchanges must be for products of equal or greater value. '
                        f'({rep_product.name} price ₹{rep_product.price:.0f} is less than returned item price ₹{item.unit_price:.0f})'
                    )

            validated_items.append({
                'bill_item': item,
                'quantity': qty,
                'condition': ri.get('condition', 'GOOD'),
                'action_type': 'EXCHANGE',
                'replacement_product': rep_product,
                'replacement_quantity': rep_qty,
            })

        cleaned['validated_return_items'] = validated_items
        return cleaned

    def save(self, user):
        bill = self.cleaned_data['invoice_id']
        reason = self.cleaned_data['reason']
        validated_items = self.cleaned_data['validated_return_items']

        from core.models import ProductRegistry, StockTransaction, ComboGroup
        returns = []
        for vi in validated_items:
            item = vi['bill_item']
            qty = vi['quantity']
            condition = vi['condition']
            action_type = vi['action_type']
            rep_product = vi['replacement_product']
            rep_qty = vi['replacement_quantity']

            # Check if combo product to determine price difference
            is_combo = item.is_combo_purchase

            if is_combo:
                price_diff = 0
            else:
                price_diff = (rep_product.price * rep_qty) - (item.unit_price * qty)

            # Create approved ReturnRequest
            ret = ReturnRequest.objects.create(
                invoice=bill,
                bill_item=item,
                product=item.product,
                quantity=qty,
                condition=condition,
                action_type=action_type,
                replacement_product=rep_product,
                replacement_quantity=rep_qty,
                price_difference=price_diff,
                requested_by=user,
                product_name=item.product.name,
                reason=reason,
                status=ReturnRequest.Status.APPROVED,
                active_branch=user.active_branch,
            )

            # Update cache/helper fields on Bill and BillItem
            item.returned_quantity += qty
            item.save()

            bill.has_returns = True
            bill.save()

            # Process stock updates directly here in a single transaction context
            # 1. Update returned product stock
            ret_registry, _ = ProductRegistry.objects.get_or_create(
                product=item.product,
                branch=bill.branch,
                defaults={'stock_quantity': 0, 'damaged_qty': 0}
            )
            if condition == 'GOOD':
                ret_registry.stock_quantity += qty
                ret_registry.save()
                StockTransaction.objects.create(
                    product=item.product,
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
                    product=item.product,
                    branch=bill.branch,
                    transaction_type='DMG',
                    quantity=qty,
                    reference=f"Return #{ret.pk} (DAMAGED)",
                    user=user
                )

            # 2. Update replacement product stock
            if rep_product:
                rep_registry, _ = ProductRegistry.objects.get_or_create(
                    product=rep_product,
                    branch=bill.branch,
                    defaults={'stock_quantity': 0, 'damaged_qty': 0}
                )
                rep_registry.stock_quantity -= rep_qty
                rep_registry.save()
                StockTransaction.objects.create(
                    product=rep_product,
                    branch=bill.branch,
                    transaction_type='OUT',
                    quantity=rep_qty,
                    reference=f"Exchange Swap for Return #{ret.pk}",
                    user=user
                )

            returns.append(ret)

        return returns
