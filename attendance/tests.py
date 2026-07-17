from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from users.models import User
from core.models import Branch
from .models import Attendance, LeaveRequest, PermissionRequest, SalaryConfig, MonthlyPayroll
import datetime

class AttendanceTestCase(TestCase):
    def setUp(self):
        # Create a branch
        self.branch = Branch.objects.create(
            name="Main Branch",
            location="Test Location",
            contact_number="1234567890"
        )
        
        # Create users
        self.owner = User.objects.create_user(
            username="owner_user",
            password="testpassword",
            role="owner"
        )
        self.staff = User.objects.create_user(
            username="staff_user",
            password="testpassword",
            role="sales_staff",
            active_branch=self.branch
        )
        self.staff.branches.add(self.branch)
        
        # Setup Salary Config
        self.salary_config = SalaryConfig.objects.create(
            user=self.staff,
            monthly_base_salary=30000.00,
            late_deduction_amount=200.00,
            lop_deduction_amount=1000.00
        )
        
        # Create client
        self.client = Client()

    def test_attendance_model_creation(self):
        today = timezone.localdate()
        att = Attendance.objects.create(
            user=self.staff,
            branch=self.branch,
            date=today,
            status="present"
        )
        self.assertEqual(att.status, "present")
        self.assertEqual(att.user.username, "staff_user")

    def test_leave_request_and_approval(self):
        today = timezone.localdate()
        leave = LeaveRequest.objects.create(
            user=self.staff,
            leave_type="emergency",
            start_date=today,
            end_date=today + datetime.timedelta(days=1),
            reason="Medical emergency",
            status="pending"
        )
        self.assertEqual(leave.status, "pending")
        
        # Approve leave view/logic
        self.client.login(username="owner_user", password="testpassword")
        response = self.client.get(reverse('attendance:leave_approve', args=[leave.pk, 'approve']))
        self.assertEqual(response.status_code, 302) # Redirect
        
        # Check leave status
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")
        
        # Check that attendance was auto-created for the dates of leave
        att_today = Attendance.objects.get(user=self.staff, date=today)
        self.assertEqual(att_today.status, "on_leave")

    def test_payroll_generation(self):
        # Let's generate a month of attendance
        today = timezone.localdate()
        month = today.month
        year = today.year
        
        # Create attendance for 2 days present, 1 day late, 1 day absent
        # 1. Present
        Attendance.objects.create(
            user=self.staff,
            branch=self.branch,
            date=datetime.date(year, month, 1),
            status="present"
        )
        # 2. Late
        Attendance.objects.create(
            user=self.staff,
            branch=self.branch,
            date=datetime.date(year, month, 2),
            status="late"
        )
        # We leave other days of the month empty (which will count as absent/LOP in payroll generator)
        
        # Run payroll generation view
        self.client.login(username="owner_user", password="testpassword")
        response = self.client.post(reverse('attendance:generate_payroll'), {
            'month': month,
            'year': year
        })
        self.assertEqual(response.status_code, 302) # Redirects back to list
        
        # Verify payroll object
        payroll = MonthlyPayroll.objects.get(user=self.staff, month=month, year=year)
        self.assertEqual(payroll.base_salary, 30000.00)
        # 1 day late deduction = 200
        # Rest of the month days are LOP. 
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        absent_days = days_in_month - 2
        lop_days_to_deduct = max(0, absent_days - 4)
        expected_deductions = (lop_days_to_deduct * 1000.00) + (1 * 200.00)
        self.assertEqual(payroll.deductions, expected_deductions)
        
        expected_net = 30000.00 - expected_deductions
        if expected_net < 0:
            expected_net = 0
            
        self.assertEqual(payroll.net_salary, expected_net)

    def test_is_manager_or_owner_includes_regional_manager(self):
        from .views import is_manager_or_owner
        regional_manager = User.objects.create_user(
            username="rm_user",
            password="testpassword",
            role="regional_manager"
        )
        self.assertTrue(is_manager_or_owner(regional_manager))

    def test_payroll_properties(self):
        # Create a MonthlyPayroll
        today = timezone.localdate()
        payroll = MonthlyPayroll.objects.create(
            user=self.staff,
            month=today.month,
            year=today.year,
            present_days=20,
            absent_days=10,
            late_days=3,
            approved_leaves=2,
            unapproved_leaves=8,
            base_salary=30000.00,
            deductions=4600.00, # (3 late * 200) + ((8 unapproved - 4 weekoff) * 1000) = 600 + 4000 = 4600
            net_salary=25400.00
        )
        self.assertEqual(payroll.late_deductions, 600.00)
        self.assertEqual(payroll.lop_days, 8)
        self.assertEqual(payroll.lop_deductions, 4000.00)

    def test_branch_invoice_prefix_auto_uniquify(self):
        # b1 will automatically uniquify to 'AG2' because self.branch created in setUp already has 'AG'
        b1 = Branch.objects.create(name="Nellore", location="Loc1")
        self.assertEqual(b1.invoice_prefix, "AG2")
        
        # b2 created without explicit invoice_prefix should automatically uniquify to 'AG3'
        b2 = Branch.objects.create(name="Tirupati", location="Loc2")
        self.assertEqual(b2.invoice_prefix, "AG3")
        
        # b3 created without explicit invoice_prefix should automatically uniquify to 'AG4'
        b3 = Branch.objects.create(name="Guntur", location="Loc3")
        self.assertEqual(b3.invoice_prefix, "AG4")

    def test_permission_request_validations(self):
        # Configure limits for the staff user: max 2 permissions per month, max 2.5 hours per request
        self.salary_config.max_permissions_per_month = 2
        self.salary_config.max_hours_per_permission = 2.50
        self.salary_config.save()

        # Login as staff user
        self.client.login(username="staff_user", password="testpassword")

        # 1. Test standard valid request (2 hours)
        response = self.client.post(reverse('attendance:permission_request'), {
            'date': '2026-07-15',
            'start_time': '10:00',
            'end_time': '12:00',
            'reason': 'Doctor appointment'
        })
        self.assertEqual(response.status_code, 302)  # Redirect
        # Check created
        self.assertEqual(PermissionRequest.objects.filter(user=self.staff).count(), 1)
        perm1 = PermissionRequest.objects.get(user=self.staff)
        self.assertEqual(perm1.reason, 'Doctor appointment')

        # 2. Test request exceeding hours limit (3 hours)
        response = self.client.post(reverse('attendance:permission_request'), {
            'date': '2026-07-16',
            'start_time': '10:00',
            'end_time': '13:00',
            'reason': 'Personal errand'
        })
        self.assertEqual(response.status_code, 302)
        # Should NOT create a second request
        self.assertEqual(PermissionRequest.objects.filter(user=self.staff).count(), 1)

        # 3. Test request exceeding monthly quota (creating 2nd valid, then 3rd should fail)
        # Create second valid request
        response = self.client.post(reverse('attendance:permission_request'), {
            'date': '2026-07-17',
            'start_time': '10:00',
            'end_time': '12:00',
            'reason': 'Bank visit'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PermissionRequest.objects.filter(user=self.staff).count(), 2)

        # Try to create third request in the same month (July 2026)
        response = self.client.post(reverse('attendance:permission_request'), {
            'date': '2026-07-18',
            'start_time': '10:00',
            'end_time': '11:00',
            'reason': 'Other errand'
        })
        self.assertEqual(response.status_code, 302)
        # Should still be only 2 requests
        self.assertEqual(PermissionRequest.objects.filter(user=self.staff).count(), 2)
