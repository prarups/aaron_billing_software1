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
            'id': 'addStaffPassword',
            'autocomplete': 'new-password'
        }),
        required=False,
        help_text="Leave blank to keep existing password when editing."
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'role', 'branches', 'employee_id', 'mobile_number', 'address', 'is_active', 'date_of_joining']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Username', 'autocomplete': 'new-username'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'First Name', 'autocomplete': 'off'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Last Name', 'autocomplete': 'off'}),
            'role': forms.Select(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light px-3', 'data-no-search': 'true'}),
            'branches': forms.SelectMultiple(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light', 'size': '6'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Employee ID (Auto-generated if blank)', 'maxlength': '10', 'autocomplete': 'off'}),
            'mobile_number': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Mobile Number', 'autocomplete': 'off'}),
            'address': forms.Textarea(attrs={'class': 'form-control rounded-3 shadow-sm border-0 bg-light px-3', 'placeholder': 'Address', 'rows': '2', 'autocomplete': 'off'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'date_of_joining': forms.DateInput(attrs={'type':'date','class':'form-control rounded-pill shadow-sm border-0 bg-light px-3','placeholder':'Date of Joining', 'autocomplete': 'off'}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password')
        # Password is optional for new accounts; if not provided, a temporary password will be generated later.
        return password

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [('owner', 'Admin'), ('manager', 'Manager'), ('assistant_manager', 'Assistant Manager'), ('sales_staff', 'Sales Staff')]
        self.fields['branches'].queryset = Branch.objects.all()
        self.fields['branches'].required = False
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
            # Enforce max length of 10 characters (matches DB column)
            if len(employee_id) > 10:
                raise forms.ValidationError("Employee ID must be at most 10 characters long.")
            # Ensure unique
            qs = User.objects.filter(employee_id__iexact=employee_id)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This Employee ID is already assigned to another user.")
        return employee_id

    def clean_date_of_joining(self):
        date = self.cleaned_data.get('date_of_joining')
        if not date:
            # Use current date as default joining date
            from django.utils import timezone
            return timezone.now().date()
        return date

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        branches = cleaned_data.get('branches')
        
        if role in ['manager', 'assistant_manager', 'sales_staff']:
            if not branches:
                self.add_error('branches', "Please select at least one branch for this account.")
            elif role == 'sales_staff' and branches.count() > 1:
                self.add_error('branches', "Sales Staff cannot be assigned to more than one branch. Please select only one branch.")
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        else:
            # Generate a temporary random password for the user
            from django.utils.crypto import get_random_string
            temp_password = get_random_string(12)
            user.set_password(temp_password)
            # Optionally, you could email this password to the user or log it for admin reference
            # Here we simply print it for debugging (remove in production)
            print(f'Generated temporary password for user {user.username}: {temp_password}')
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




