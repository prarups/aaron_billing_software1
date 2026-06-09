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
            role="staff",
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
            'role': 'staff',
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
            'role': 'staff',
            'branches': [self.branch1.id],
            'mobile_number': '1234567890',
            'address': '123 Street Name',
            'is_active': True
        })
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.mobile_number, '1234567890')
        self.assertEqual(user.address, '123 Street Name')

