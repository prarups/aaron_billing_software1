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
