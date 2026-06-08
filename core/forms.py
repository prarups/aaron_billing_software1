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
        
        # If editing an existing product, make master details (name, barcode, size) read-only
        if self.instance and self.instance.pk:
            self.fields['name'].disabled = True
            self.fields['barcode'].disabled = True
            self.fields['size'].disabled = True

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None:
            # Convert to integer value (remove decimals)
            return int(price)
        return price

# Inline ComboPrice form and formset
class ComboPriceForm(forms.ModelForm):
    class Meta:
        model = ComboPrice
        fields = ['quantity', 'price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control rounded-pill'}),
            'price': forms.NumberInput(attrs={'class': 'form-control rounded-pill', 'step': '1'}),
        }

ComboPriceFormSet = inlineformset_factory(
    Product,
    ComboPrice,
    form=ComboPriceForm,
    fields=['quantity', 'price'],
    extra=0,
    can_delete=True,
)

