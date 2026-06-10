from django import forms
from django.forms import inlineformset_factory
from .models import Branch, Product, ComboPrice


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'location', 'contact_number', 'invoice_prefix']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
            'location': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
            'invoice_prefix': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            qs = Branch.objects.filter(name__iexact=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A branch with this name already exists.")
        return name

    def clean_invoice_prefix(self):
        prefix = self.cleaned_data.get('invoice_prefix')
        if prefix:
            qs = Branch.objects.filter(invoice_prefix__iexact=prefix)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A branch with this invoice prefix already exists.")
        return prefix

# Existing ProductForm (preserve previous definition). If the file already exists, this will overwrite; ensure to keep original content.

class ProductForm(forms.ModelForm):
    initial_branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        required=False,
        empty_label=None,
        label="Branch Location",
        widget=forms.Select(attrs={
            'autocomplete': 'off',
            'placeholder': 'Select a branch',
            'data-placeholder': 'Select a branch',
        })
    )
    initial_stock = forms.IntegerField(
        required=False,
        initial=0,
        min_value=0,
        label="Initial Stock Quantity",
        widget=forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'min': '0'})
    )
    low_stock_threshold = forms.IntegerField(
        required=False,
        initial=10,
        min_value=0,
        label="Low Stock Alert Level",
        widget=forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'min': '0'})
    )
    class Meta:
        model = Product
        fields = ['name', 'barcode', 'price', 'size']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
            'price': forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'step': '1'}),
            'size': forms.TextInput(attrs={'class': 'form-control rounded-pill'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure branch dropdown shows the branch name
        self.fields['initial_branch'].label_from_instance = lambda obj: obj.name

    def clean(self):
        cleaned_data = super().clean()
        barcode = cleaned_data.get('barcode')
        branch = getattr(self.instance, 'branch', None)
        
        if barcode and branch:
            qs = Product.objects.filter(branch=branch, barcode__iexact=barcode)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('barcode', f"Product with barcode '{barcode}' already exists for this branch.")
        return cleaned_data

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None:
            if price < 0:
                raise forms.ValidationError("Price cannot be negative.")
            # Convert to integer value (remove decimals)
            return int(price)
        return price

# Inline ComboPrice form and formset
class ComboPriceForm(forms.ModelForm):
    class Meta:
        model = ComboPrice
        fields = ['quantity', 'price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'min': '1'}),
            'price': forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'step': '1', 'min': '0'}),
        }

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is not None and qty < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return qty

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return price

ComboPriceFormSet = inlineformset_factory(
    Product,
    ComboPrice,
    form=ComboPriceForm,
    fields=['quantity', 'price'],
    extra=0,
    can_delete=True,
)

