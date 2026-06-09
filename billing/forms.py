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
        widget=forms.NumberInput(attrs={
            'class': 'form-control rounded-pill border-0 bg-light',
            'min': '1',
            'step': '1',
        })
    )
    condition = forms.ChoiceField(
        label='Product Condition',
        choices=ReturnRequest.CONDITION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select rounded-pill border-0 bg-light',
        })
    )
    action_type = forms.ChoiceField(
        label='Return Action',
        choices=[
            ('EXCH_SAME', 'Exchange with same item (Another one)')
        ],
        initial='EXCH_SAME',
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
            if item:
                return_items = [{
                    'id': item.id,
                    'quantity': qty,
                    'condition': cleaned.get('condition', 'GOOD'),
                    'action_type': cleaned.get('action_type', 'EXCH_SAME')
                }]
            else:
                raise forms.ValidationError('Please add at least one product to the return list.')

        # Validate each item in the return list
        validated_items = []
        for ri in return_items:
            try:
                item_id = int(ri['id'])
                qty = int(ri['quantity'])
            except (ValueError, KeyError, TypeError):
                raise forms.ValidationError('Invalid product or quantity in return list.')

            if qty < 1:
                raise forms.ValidationError('Return quantity must be at least 1.')

            try:
                item = BillItem.objects.select_related('product').get(id=item_id)
            except BillItem.DoesNotExist:
                raise forms.ValidationError('Product item not found.')

            if item.bill_id != bill.id:
                raise forms.ValidationError(f'Product {item.product.name} does not belong to this bill.')

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

            validated_items.append({
                'bill_item': item,
                'quantity': qty,
                'condition': ri.get('condition', 'GOOD'),
                'action_type': ri.get('action_type', 'EXCH_SAME')
            })

        cleaned['validated_return_items'] = validated_items
        return cleaned

    def save(self, user):
        bill = self.cleaned_data['invoice_id']
        reason = self.cleaned_data['reason']
        validated_items = self.cleaned_data['validated_return_items']

        returns = []
        for vi in validated_items:
            item = vi['bill_item']
            qty = vi['quantity']
            condition = vi['condition']
            action_type = vi['action_type']

            # Calculate refund amount
            refund_amount = item.unit_price * qty

            # Create approved ReturnRequest
            ret = ReturnRequest.objects.create(
                invoice=bill,
                bill_item=item,
                product=item.product,
                quantity=qty,
                condition=condition,
                action_type=action_type,
                requested_by=user,
                product_name=item.product.name,
                reason=reason,
                status=ReturnRequest.Status.APPROVED,
                active_branch=user.active_branch,
            )

            # Create CreditNote only for REFUND actions
            if action_type == 'REFUND':
                CreditNote.objects.create(
                    invoice=bill,
                    amount=refund_amount,
                    reason=reason,
                    issued_by=user,
                )

            returns.append(ret)

        return returns
