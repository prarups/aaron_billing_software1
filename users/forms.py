from django import forms
from django.contrib.auth.forms import AuthenticationForm
from core.models import Branch
from .models import User

class CustomAuthenticationForm(AuthenticationForm):
    def clean(self):
        username_input = self.cleaned_data.get('username')
        if username_input:
            # Check if the input username matches an employee_id (case-insensitive)
            user_by_emp = User.objects.filter(employee_id__iexact=username_input).first()
            if user_by_emp:
                self.cleaned_data['username'] = user_by_emp.username

        cleaned_data = super().clean()
        user = self.get_user()
        
        if user:
            # Check if account is active
            if not user.is_active:
                raise forms.ValidationError("Your account is inactive. Please contact admin team.")
            
            # Auto-assign active branch for manager and staff roles
            if not user.is_owner():
                accessible_branches = user.get_accessible_branches()
                if accessible_branches.exists():
                    # Default active_branch to the first branch they are assigned to if not set or valid
                    if not user.active_branch or user.active_branch not in accessible_branches:
                        user.active_branch = accessible_branches.first()
                        user.save(update_fields=['active_branch'])
                else:
                    if user.active_branch:
                        user.active_branch = None
                        user.save(update_fields=['active_branch'])
        return cleaned_data


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name', 'location', 'contact_number', 'invoice_prefix']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Branch Name'}),
            'location': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Location Address'}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Contact Number'}),
            'invoice_prefix': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Invoice Prefix (e.g. AG)'}),
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
class StaffForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3',
            'placeholder': 'Password',
            'id': 'addStaffPassword'
        }),
        required=False,
        help_text="Leave blank to keep existing password when editing."
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'role', 'branches', 'employee_id', 'mobile_number', 'address', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Username'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Last Name'}),
            'role': forms.Select(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light px-3', 'data-no-search': 'true'}),
            'branches': forms.SelectMultiple(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light', 'size': '6'}),
            'mobile_number': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Mobile Number'}),
            'address': forms.Textarea(attrs={'class': 'form-control rounded-3 shadow-sm border-0 bg-light px-3', 'placeholder': 'Address', 'rows': '2'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.instance.pk and not password:
            raise forms.ValidationError("Password is required for new accounts.")
        return password

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [('owner', 'Admin'), ('manager', 'Manager'), ('staff', 'Staff')]
        self.fields['branches'].queryset = Branch.objects.all()
        # Employee ID is optional on form input as it will auto‑generate if blank
        self.fields['employee_id'].required = False
        # Make employee_id read‑only on edit
        if self.instance.pk:
            self.fields['employee_id'].widget.attrs['readonly'] = True
            self.fields['employee_id'].disabled = True

        self.fields['mobile_number'].required = True


    def clean_is_active(self):
        is_active = self.cleaned_data.get('is_active')
        if self.instance.pk and 'is_active' not in self.data:
            return self.instance.is_active
        return is_active

    def clean_employee_id(self):
        employee_id = self.cleaned_data.get('employee_id')
        if employee_id:
            # Ensure unique
            qs = User.objects.filter(employee_id__iexact=employee_id)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This Employee ID is already assigned to another user.")
        return employee_id

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        branches = cleaned_data.get('branches')
        # Enforce at least one branch for managers and staff
        if role in ['manager', 'staff'] and (not branches or len(branches) == 0):
            raise forms.ValidationError(
                "Managers and Staff must be assigned at least one branch."
            )
        # Only owners and managers can be assigned multiple branches
        if role not in ['owner', 'manager'] and branches and len(branches) > 1:
            raise forms.ValidationError(
                "Only managers and admins can be assigned multiple branches."
            )
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if user.role == 'owner':
            user.is_superuser = True
            user.is_staff = True
        else:
            user.is_superuser = False
            user.is_staff = False
        if commit:
            user.save()
            self.save_m2m()
        return user




