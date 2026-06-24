from django.test import TestCase, RequestFactory
from django.contrib.admin import AdminSite
from core.models import Branch, Product, ProductRegistry, StockTransaction, StockAdjustment
from core.admin import BranchAdmin, ProductAdmin, ProductRegistryAdmin, StockTransactionAdmin, StockAdjustmentAdmin
from billing.models import Bill
from billing.admin import BillAdmin
from users.models import User
from users.admin import CustomUserAdmin

class AdminPermissionsTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        
        # Create a test branch
        self.branch1 = Branch.objects.create(name="Nellore", code="10001", invoice_prefix="NL")
        self.branch2 = Branch.objects.create(name="Tirupati", code="10002", invoice_prefix="TP")
        
        # Create users
        self.owner = User.objects.create_user(
            username="test_owner",
            password="password123",
            role="owner",
            is_staff=True,
            is_superuser=False
        )
        self.owner.branches.add(self.branch1, self.branch2)
        
        self.manager_with_rights = User.objects.create_user(
            username="mgr_rights",
            password="password123",
            role="manager",
            is_staff=True,
            is_superuser=False,
            has_product_rights=True
        )
        self.manager_with_rights.branches.add(self.branch1)
        
        self.manager_no_rights = User.objects.create_user(
            username="mgr_norights",
            password="password123",
            role="manager",
            is_staff=True,
            is_superuser=False,
            has_product_rights=False
        )
        self.manager_no_rights.branches.add(self.branch1)

        # Create some test bills
        self.bill1 = Bill.objects.create(branch=self.branch1, staff=self.owner, total_amount=100)
        self.bill2 = Bill.objects.create(branch=self.branch2, staff=self.owner, total_amount=200)

    def test_owner_admin_permissions(self):
        # Setup request for owner
        request = self.factory.get('/admin')
        request.user = self.owner
        
        # 1. BranchAdmin
        branch_admin = BranchAdmin(Branch, self.admin_site)
        self.assertTrue(branch_admin.has_view_permission(request))
        self.assertTrue(branch_admin.has_add_permission(request))
        self.assertTrue(branch_admin.has_change_permission(request))
        self.assertTrue(branch_admin.has_delete_permission(request))
        # get_queryset should return all branches
        self.assertEqual(list(branch_admin.get_queryset(request).order_by('id')), list(Branch.objects.all().order_by('id')))
        
        # 2. ProductAdmin
        product_admin = ProductAdmin(Product, self.admin_site)
        self.assertTrue(product_admin.has_view_permission(request))
        self.assertTrue(product_admin.has_add_permission(request))
        self.assertTrue(product_admin.has_change_permission(request))
        self.assertTrue(product_admin.has_delete_permission(request))
        
        # 3. ProductRegistryAdmin
        registry_admin = ProductRegistryAdmin(ProductRegistry, self.admin_site)
        self.assertTrue(registry_admin.has_view_permission(request))
        self.assertTrue(registry_admin.has_add_permission(request))
        self.assertTrue(registry_admin.has_change_permission(request))
        self.assertTrue(registry_admin.has_delete_permission(request))
        
        # 4. StockTransactionAdmin
        tx_admin = StockTransactionAdmin(StockTransaction, self.admin_site)
        self.assertTrue(tx_admin.has_view_permission(request))
        self.assertTrue(tx_admin.has_add_permission(request))
        self.assertTrue(tx_admin.has_change_permission(request))
        self.assertTrue(tx_admin.has_delete_permission(request))
        
        # 5. StockAdjustmentAdmin
        adj_admin = StockAdjustmentAdmin(StockAdjustment, self.admin_site)
        self.assertTrue(adj_admin.has_view_permission(request))
        self.assertTrue(adj_admin.has_add_permission(request))
        self.assertTrue(adj_admin.has_change_permission(request))
        self.assertTrue(adj_admin.has_delete_permission(request))
        
        # 6. BillAdmin
        bill_admin = BillAdmin(Bill, self.admin_site)
        self.assertTrue(bill_admin.has_view_permission(request))
        # get_queryset should return all bills
        self.assertEqual(list(bill_admin.get_queryset(request).order_by('id')), list(Bill.objects.all().order_by('id')))
        
        # 7. CustomUserAdmin
        user_admin = CustomUserAdmin(User, self.admin_site)
        self.assertTrue(user_admin.has_view_permission(request))
        self.assertTrue(user_admin.has_add_permission(request))
        self.assertTrue(user_admin.has_change_permission(request))
        self.assertTrue(user_admin.has_delete_permission(request))

    def test_manager_admin_permissions(self):
        # Manager with product rights
        request_rights = self.factory.get('/admin')
        request_rights.user = self.manager_with_rights
        
        # Manager without product rights
        request_norights = self.factory.get('/admin')
        request_norights.user = self.manager_no_rights
        
        # Product permissions check
        product_admin = ProductAdmin(Product, self.admin_site)
        
        self.assertTrue(product_admin.has_view_permission(request_rights))
        self.assertTrue(product_admin.has_add_permission(request_rights))
        self.assertTrue(product_admin.has_change_permission(request_rights))
        self.assertTrue(product_admin.has_delete_permission(request_rights))
        
        self.assertTrue(product_admin.has_view_permission(request_norights))
        self.assertFalse(product_admin.has_add_permission(request_norights))
        self.assertFalse(product_admin.has_change_permission(request_norights))
        self.assertFalse(product_admin.has_delete_permission(request_norights))

        # Branch permissions check
        branch_admin = BranchAdmin(Branch, self.admin_site)
        self.assertTrue(branch_admin.has_view_permission(request_rights))
        self.assertTrue(branch_admin.has_add_permission(request_rights))
        self.assertTrue(branch_admin.has_change_permission(request_rights))
        self.assertTrue(branch_admin.has_delete_permission(request_rights))
        
        # Manager should only see their accessible branches in get_queryset
        self.assertEqual(list(branch_admin.get_queryset(request_rights)), [self.branch1])


class BranchValidationTestCase(TestCase):
    def setUp(self):
        # Create an initial branch
        self.branch = Branch.objects.create(
            name="Original Branch",
            location="Nellore",
            contact_number="9876543210",
            invoice_prefix="OB"
        )

    def test_branch_form_duplicate_name(self):
        from users.forms import BranchForm
        
        # Test exact match name duplicate
        form = BranchForm(data={
            'name': "Original Branch",
            'location': "Tirupati",
            'invoice_prefix': "TB"
        })
        self.assertFalse(form.is_valid())
        self.assertIn("A branch with this name already exists.", form.errors['name'])
        
        # Test case-insensitive duplicate name
        form_ci = BranchForm(data={
            'name': "original branch",
            'location': "Tirupati",
            'invoice_prefix': "TB"
        })
        self.assertFalse(form_ci.is_valid())
        self.assertIn("A branch with this name already exists.", form_ci.errors['name'])

    def test_branch_form_duplicate_prefix(self):
        from users.forms import BranchForm
        
        # Test exact match prefix duplicate
        form = BranchForm(data={
            'name': "Unique Branch",
            'location': "Tirupati",
            'invoice_prefix': "OB"
        })
        self.assertFalse(form.is_valid())
        self.assertIn("A branch with this invoice prefix already exists.", form.errors['invoice_prefix'])
        
        # Test case-insensitive duplicate prefix
        form_ci = BranchForm(data={
            'name': "Unique Branch",
            'location': "Tirupati",
            'invoice_prefix': "ob"
        })
        self.assertFalse(form_ci.is_valid())
        self.assertIn("A branch with this invoice prefix already exists.", form_ci.errors['invoice_prefix'])

    def test_branch_form_edit_self_succeeds(self):
        from users.forms import BranchForm
        
        # Editing same branch with same name/prefix should be allowed
        form = BranchForm(instance=self.branch, data={
            'name': "Original Branch",
            'location': "Nellore New Address",
            'invoice_prefix': "OB"
        })
        self.assertTrue(form.is_valid())

    def test_branch_form_edit_other_duplicate_fails(self):
        from users.forms import BranchForm
        other_branch = Branch.objects.create(
            name="Other Branch",
            location="Guntur",
            invoice_prefix="OT"
        )
        
        # Attempt to rename other_branch to self.branch's name
        form = BranchForm(instance=other_branch, data={
            'name': "Original Branch",
            'location': "Guntur",
            'invoice_prefix': "OT"
        })
        self.assertFalse(form.is_valid())
        self.assertIn("A branch with this name already exists.", form.errors['name'])


class LoginAuthenticationTestCase(TestCase):
    def setUp(self):
        self.branch1 = Branch.objects.create(name="Nellore", code="10001", invoice_prefix="NL")
        self.staff_user = User.objects.create_user(
            username="johndoe",
            password="password123",
            role="sales_staff",
            is_active=True
        )
        self.staff_user.branches.add(self.branch1)

    def test_login_by_username(self):
        from users.forms import CustomAuthenticationForm
        form = CustomAuthenticationForm(data={
            'username': 'johndoe',
            'password': 'password123'
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_user(), self.staff_user)
        # Check active branch is auto-assigned
        self.assertEqual(form.get_user().active_branch, self.branch1)

    def test_login_by_employee_id(self):
        from users.forms import CustomAuthenticationForm
        emp_id = self.staff_user.employee_id
        self.assertTrue(emp_id.startswith("AR"))
        
        # Test case-insensitive login by employee_id
        form = CustomAuthenticationForm(data={
            'username': emp_id.lower(),
            'password': 'password123'
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(form.get_user(), self.staff_user)
        # Check active branch is auto-assigned
        self.assertEqual(form.get_user().active_branch, self.branch1)


class StaffFormTestCase(TestCase):
    def setUp(self):
        self.branch1 = Branch.objects.create(name="Nellore", code="10001", invoice_prefix="NL")

    def test_staff_form_missing_mobile_number(self):
        from users.forms import StaffForm
        form = StaffForm(data={
            'username': 'newstaff',
            'first_name': 'New',
            'last_name': 'Staff',
            'password': 'password123',
            'role': 'sales_staff',
            'branches': [self.branch1.id],
            'is_active': True
        })
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_number', form.errors)

    def test_staff_form_valid(self):
        from users.forms import StaffForm
        form = StaffForm(data={
            'username': 'newstaff',
            'first_name': 'New',
            'last_name': 'Staff',
            'password': 'password123',
            'role': 'sales_staff',
            'branches': [self.branch1.id],
            'mobile_number': '1234567890',
            'address': '123 Street Name',
            'is_active': True
        })
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.mobile_number, '1234567890')
        self.assertEqual(user.address, '123 Street Name')


class ToggleBillEditRightsTestCase(TestCase):
    def setUp(self):
        self.branch1 = Branch.objects.create(name="Nellore", code="10001", invoice_prefix="NL")
        self.owner = User.objects.create_user(
            username="owner_user",
            password="password123",
            role="owner",
            is_staff=True
        )
        self.staff_user = User.objects.create_user(
            username="staff_user",
            password="password123",
            role="sales_staff"
        )
        self.staff_user.branches.add(self.branch1)

    def test_toggle_bill_edit_rights_success(self):
        self.client.login(username="owner_user", password="password123")
        self.assertFalse(self.staff_user.has_bill_edit_rights)
        
        response = self.client.post(
            f"/users/staff/toggle-bill-edit-rights/{self.staff_user.id}/",
            data='{"has_bill_edit_rights": true}',
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.staff_user.refresh_from_db()
        self.assertTrue(self.staff_user.has_bill_edit_rights)

    def test_toggle_bill_edit_rights_denied(self):
        self.client.login(username="staff_user", password="password123")
        response = self.client.post(
            f"/users/staff/toggle-bill-edit-rights/{self.staff_user.id}/",
            data='{"has_bill_edit_rights": true}',
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)


class BranchSortingTestCase(TestCase):
    def setUp(self):
        # Delete any existing branches to avoid collision
        Branch.objects.all().delete()
        # Create branches with out-of-order codes
        self.branch_c = Branch.objects.create(name="Branch C", code=10003, invoice_prefix="AC")
        self.branch_a = Branch.objects.create(name="Branch A", code=10001, invoice_prefix="AA")
        self.branch_b = Branch.objects.create(name="Branch B", code=10002, invoice_prefix="AB")
        
        # Owner user
        self.owner = User.objects.create_user(
            username="owner_user_sorting", 
            password="password123", 
            role="owner",
            is_staff=True
        )

    def test_owner_dashboard_branches_sorted_by_code(self):
        self.client.login(username="owner_user_sorting", password="password123")
        from django.urls import reverse
        url = reverse('owner_dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        branches_by_code = response.context['branches_by_code']
        # Extract codes
        codes = [b.code for b in branches_by_code]
        # Should be in ascending order
        self.assertEqual(codes, [10001, 10002, 10003])


class ExportCSVTestCase(TestCase):
    def setUp(self):
        # Clean existing branches/users
        Branch.objects.all().delete()
        self.branch = Branch.objects.create(name="Nellore Branch", code=10001, invoice_prefix="AN")
        self.owner = User.objects.create_user(
            username="owner_user_export", 
            password="password123", 
            role="owner",
            is_staff=True
        )
        self.staff = User.objects.create_user(
            username="staff_user_export", 
            password="password123", 
            role="sales_staff"
        )

    def test_export_branches_csv_as_owner(self):
        self.client.login(username="owner_user_export", password="password123")
        from django.urls import reverse
        url = reverse('export_branches_csv')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertTrue('branches_report.csv' in response['Content-Disposition'])

    def test_export_branches_csv_as_staff_denied(self):
        self.client.login(username="staff_user_export", password="password123")
        from django.urls import reverse
        url = reverse('export_branches_csv')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_export_staff_csv_as_owner(self):
        self.client.login(username="owner_user_export", password="password123")
        from django.urls import reverse
        url = reverse('export_staff_csv')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertTrue('sales_staff_accounts.csv' in response['Content-Disposition'])

    def test_export_staff_csv_as_staff_denied(self):
        self.client.login(username="staff_user_export", password="password123")
        from django.urls import reverse
        url = reverse('export_staff_csv')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class StaffFormBranchValidationTestCase(TestCase):
    def setUp(self):
        # Clean up database to prevent uniqueness collisions
        Branch.objects.all().delete()
        User.objects.all().delete()
        self.branch1 = Branch.objects.create(name="Branch One", code=10001, invoice_prefix="AA")
        self.branch2 = Branch.objects.create(name="Branch Two", code=10002, invoice_prefix="AB")

    def test_clean_validation_no_branches_fails(self):
        from users.forms import StaffForm
        data = {
            'username': 'newstaff1',
            'role': 'sales_staff',
            'branches': [],
            'mobile_number': '1234567890'
        }
        form = StaffForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertTrue('branches' in form.errors)
        self.assertEqual(form.errors['branches'][0], "Please select at least one branch for this account.")

    def test_clean_validation_staff_multiple_branches_fails(self):
        from users.forms import StaffForm
        data = {
            'username': 'newstaff2',
            'role': 'sales_staff',
            'branches': [self.branch1.id, self.branch2.id],
            'mobile_number': '1234567890'
        }
        form = StaffForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertTrue('branches' in form.errors)
        self.assertEqual(form.errors['branches'][0], "Sales Staff cannot be assigned to more than one branch. Please select only one branch.")

    def test_clean_validation_staff_single_branch_succeeds(self):
        from users.forms import StaffForm
        data = {
            'username': 'newstaff3',
            'role': 'sales_staff',
            'branches': [self.branch1.id],
            'mobile_number': '1234567890'
        }
        form = StaffForm(data=data)
        self.assertTrue(form.is_valid())

    def test_clean_validation_manager_multiple_branches_succeeds(self):
        from users.forms import StaffForm
        data = {
            'username': 'newmanager1',
            'role': 'manager',
            'branches': [self.branch1.id, self.branch2.id],
            'mobile_number': '1234567890'
        }
        form = StaffForm(data=data)
        self.assertTrue(form.is_valid())


class StaffFormPasswordTestCase(TestCase):
    def setUp(self):
        Branch.objects.all().delete()
        User.objects.all().delete()
        self.branch = Branch.objects.create(name="Branch One", code=10001, invoice_prefix="AA")

    def test_create_user_with_password(self):
        from users.forms import StaffForm
        data = {
            'username': 'staff1',
            'role': 'sales_staff',
            'branches': [self.branch.id],
            'mobile_number': '1234567890',
            'password': 'mypassword123'
        }
        form = StaffForm(data=data)
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertTrue(user.check_password('mypassword123'))

    def test_create_user_without_password_generates_temp(self):
        from users.forms import StaffForm
        data = {
            'username': 'staff2',
            'role': 'sales_staff',
            'branches': [self.branch.id],
            'mobile_number': '1234567890',
            'password': ''
        }
        form = StaffForm(data=data)
        self.assertTrue(form.is_valid())
        user = form.save()
        # Since no password was provided, a random password should have been set.
        # It shouldn't be unusable/empty.
        self.assertTrue(user.has_usable_password())

    def test_edit_user_leaving_password_blank_preserves_password(self):
        from users.forms import StaffForm
        # Create user first
        user = User.objects.create_user(
            username='staff3',
            password='originalpassword123',
            role='sales_staff',
            mobile_number='1234567890'
        )
        user.branches.add(self.branch)
        
        # Form for editing
        data = {
            'username': 'staff3_updated',
            'role': 'sales_staff',
            'branches': [self.branch.id],
            'mobile_number': '9999999999',
            'password': '' # Leaving password blank
        }
        form = StaffForm(data=data, instance=user)
        self.assertTrue(form.is_valid())
        updated_user = form.save()
        
        # Verify other fields updated
        self.assertEqual(updated_user.username, 'staff3_updated')
        self.assertEqual(updated_user.mobile_number, '9999999999')
        # Verify original password is still valid!
        self.assertTrue(updated_user.check_password('originalpassword123'))

    def test_edit_user_changing_password(self):
        from users.forms import StaffForm
        # Create user first
        user = User.objects.create_user(
            username='staff4',
            password='originalpassword123',
            role='sales_staff',
            mobile_number='1234567890'
        )
        user.branches.add(self.branch)
        
        # Form for editing with a new password
        data = {
            'username': 'staff4',
            'role': 'sales_staff',
            'branches': [self.branch.id],
            'mobile_number': '1234567890',
            'password': 'newpassword123'
        }
        form = StaffForm(data=data, instance=user)
        self.assertTrue(form.is_valid())
        updated_user = form.save()
        
        # Verify password changed
        self.assertTrue(updated_user.check_password('newpassword123'))
        self.assertFalse(updated_user.check_password('originalpassword123'))


