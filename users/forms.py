from django import forms
from django.contrib.auth.forms import AuthenticationForm
from core.models import Branch
from .models import User

class CustomAuthenticationForm(AuthenticationForm):
    ROLE_CHOICES = (
        ('owner', 'Admin'),
        ('manager', 'Manager'),
        ('staff', 'Staff'),
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'})
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.all(),
        required=False,
        empty_label="Select Unique Branch",
        widget=forms.Select(attrs={'class': 'form-select rounded-3'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Auto-select branch if only one exists
        branches = Branch.objects.all()
        if branches.count() == 1:
            self.initial['branch'] = branches.first()
            self.fields['branch'].initial = branches.first()

    def clean(self):
        cleaned_data = super().clean()
        user = self.get_user()
        
        if user:
            # Check if account is active
            if not user.is_active:
                raise forms.ValidationError("Your account is inactive. Please contact admin team.")
            role_selected = cleaned_data.get('role')
            branch_selected = cleaned_data.get('branch')

            # Ensure the user has the selected role
            if user.role != role_selected:
                raise forms.ValidationError("You do not have the required permissions for this role.")

            # Owner does not need to select a branch.
            if user.is_owner():
                pass  # Owner can log in without selecting a branch
            elif not branch_selected:
                raise forms.ValidationError("Please select a branch to login.")
            else:
                # Verify user is assigned to this branch
                if not user.branches.filter(id=branch_selected.id).exists():
                    raise forms.ValidationError(f"You are not assigned to the {branch_selected.name} branch.")

                # Update user's active branch
                user.active_branch = branch_selected
                user.save()
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
class StaffForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Password'}),
        required=False,
        help_text="Leave blank to keep existing password when editing."
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'role', 'branches', 'employee_id', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Username'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control rounded-pill shadow-sm border-0 bg-light px-3', 'placeholder': 'Last Name'}),
            'role': forms.Select(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light px-3', 'data-no-search': 'true'}),
            'branches': forms.SelectMultiple(attrs={'class': 'form-select rounded-pill shadow-sm border-0 bg-light', 'size': '6'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [('owner', 'Admin'), ('manager', 'Manager'), ('staff', 'Staff')]
        self.fields['branches'].queryset = Branch.objects.all()
        # Employee ID is optional on form input as it will auto-generate if blank
        self.fields['employee_id'].required = False

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.instance.pk and not password:
            raise forms.ValidationError("Password is required for new accounts.")
        return password

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
        if role not in ['owner', 'manager'] and branches and len(branches) > 1:
            raise forms.ValidationError('Only managers and admins can be assigned multiple branches.')
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




