from django.db import models
from django.conf import settings
from decimal import Decimal
class Attendance(models.Model):
    STATUS_CHOICES = (
        ('checked_in', 'Checked In'),
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('on_leave', 'On Leave'),
        ('week_off', 'Week Off'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendances')
    branch = models.ForeignKey('core.Branch', on_delete=models.CASCADE)
    date = models.DateField()
    
    # 1. Check-In Details
    check_in = models.DateTimeField(null=True, blank=True)
    check_in_photo = models.ImageField(upload_to='attendance_photos/check_in/', null=True, blank=True)
    check_in_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # 2. Mid-Day Verification (2nd Capture)
    mid_day_time = models.DateTimeField(null=True, blank=True)
    mid_day_photo = models.ImageField(upload_to='attendance_photos/mid_day/', null=True, blank=True)
    mid_day_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    mid_day_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # 3. Check-Out Details
    check_out = models.DateTimeField(null=True, blank=True)
    check_out_photo = models.ImageField(upload_to='attendance_photos/check_out/', null=True, blank=True)
    check_out_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True, null=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='edited_attendances')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"

    def recalculate_status(self):
        """
        Calculates and returns the appropriate status for an Attendance record based on:
        - Approved Leave Requests
        - User / Role Shift timings (shift_start_time & shift_end_time)
        - Check-in delay vs grace period (Permission Requests)
        - Check-out / worked duration vs shift length (Half Day / Absent / Present)
        """
        from attendance.models import LeaveRequest, PermissionRequest, GlobalPermissionPolicy
        from users.models import RoleShiftPolicy
        import datetime
        from django.utils import timezone

        # 1. Leave Check
        on_leave = LeaveRequest.objects.filter(
            user=self.user,
            start_date__lte=self.date,
            end_date__gte=self.date,
            status='approved'
        ).exists()
        if on_leave:
            self.status = 'on_leave'
            return self.status

        # 2. Get User / Role Shift Timings
        shift_start = self.user.shift_start_time
        shift_end = self.user.shift_end_time
        if not shift_start or not shift_end:
            try:
                policy = RoleShiftPolicy.get_policy_for_role(self.user.role)
                shift_start = shift_start or policy.shift_start_time
                shift_end = shift_end or policy.shift_end_time
            except Exception:
                pass
        
        if not shift_start:
            shift_start = datetime.time(9, 0)
        if not shift_end:
            shift_end = datetime.time(17, 0)

        global_policy = GlobalPermissionPolicy.get_policy()
        grace_mins = global_policy.grace_period_minutes or 15

        # 3. Check-In Late Evaluation
        is_late_check_in = False
        if self.check_in:
            check_in_local = timezone.localtime(self.check_in)
            shift_datetime = timezone.make_aware(
                datetime.datetime.combine(self.date, shift_start),
                timezone.get_current_timezone()
            )
            delay_mins = (check_in_local - shift_datetime).total_seconds() / 60.0

            if delay_mins > grace_mins:
                has_approved_perm = PermissionRequest.objects.filter(
                    user=self.user,
                    date=self.date,
                    status='approved'
                ).exists()
                if not has_approved_perm:
                    is_late_check_in = True

        # 4. Check-Out / Worked Duration Evaluation
        today = timezone.localdate()
        if self.check_in and self.check_out:
            worked_mins = (self.check_out - self.check_in).total_seconds() / 60.0
            
            start_mins = shift_start.hour * 60 + shift_start.minute
            end_mins = shift_end.hour * 60 + shift_end.minute
            if end_mins <= start_mins:
                end_mins += 24 * 60  # Overnight shift

            shift_duration_mins = end_mins - start_mins
            half_day_threshold_mins = shift_duration_mins / 2.0
            full_day_threshold_mins = max(shift_duration_mins - grace_mins, shift_duration_mins - 30.0)

            if worked_mins < half_day_threshold_mins:
                self.status = 'absent'
            elif worked_mins < full_day_threshold_mins or is_late_check_in:
                self.status = 'half_day'
            else:
                self.status = 'present'
        elif self.check_in and self.date < today:
            # Past date record where employee forgot check-out
            if is_late_check_in:
                self.status = 'half_day'
            else:
                self.status = 'present'
        else:
            # Active check-in for current day (checkout not logged yet)
            # Show status as 'checked_in'; calculate final status (present/half_day/absent) after checkout or day end
            self.status = 'checked_in'

        return self.status



class AttendanceAuditLog(models.Model):
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE, related_name='audit_logs')
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='attendance_edits')
    timestamp = models.DateTimeField(auto_now_add=True)
    old_status = models.CharField(max_length=50, blank=True, null=True)
    new_status = models.CharField(max_length=50)
    old_check_in_time = models.TimeField(null=True, blank=True)
    new_check_in_time = models.TimeField(null=True, blank=True)
    old_check_out_time = models.TimeField(null=True, blank=True)
    new_check_out_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Attendance Audit Log'
        verbose_name_plural = 'Attendance Audit Logs'

    def __str__(self):
        return f"{self.attendance.user.username} - {self.attendance.date} edited by {self.edited_by.username if self.edited_by else 'System'}"



class LeaveRequest(models.Model):
    LEAVE_TYPES = (
        ('emergency', 'Emergency Leave'),
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leaves')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_leaves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.leave_type} ({self.start_date} to {self.end_date}) - {self.status}"


class PermissionRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='permissions')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_permissions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - Permission on {self.date} ({self.start_time} - {self.end_time}) - {self.status}"


def format_duration_display(hours_val):
    try:
        hours = float(hours_val)
        h = int(hours)
        m = int(round((hours - h) * 60))
        if h > 0 and m > 0:
            return f"{h} Hour{'s' if h > 1 else ''} {m} Mins"
        elif h > 0:
            return f"{h} Hour{'s' if h > 1 else ''}"
        elif m > 0:
            return f"{m} Mins"
        return f"{hours} Hours"
    except Exception:
        return f"{hours_val} Hours"


class GlobalPermissionPolicy(models.Model):
    max_permissions_per_month = models.IntegerField(default=2, help_text="Maximum permission requests allowed per month for all employees")
    max_hours_per_permission = models.DecimalField(max_digits=4, decimal_places=2, default=2.00, help_text="Maximum hours allowed per permission request for all employees")
    late_threshold_for_half_day_deduction = models.IntegerField(default=1, help_text="Number of late check-ins per month that trigger half-day salary deduction")
    grace_period_minutes = models.IntegerField(default=15, help_text="Global grace period in minutes before marked Late")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Global Permission Policy"
        verbose_name_plural = "Global Permission Policies"

    def __str__(self):
        return f"Global Policy: {self.max_permissions_per_month} per month, max {self.formatted_max_hours}"

    @property
    def formatted_max_hours(self):
        return format_duration_display(self.max_hours_per_permission)

    @classmethod
    def get_policy(cls):
        policy, _ = cls.objects.get_or_create(id=1, defaults={
            'max_permissions_per_month': 2,
            'max_hours_per_permission': 2.00,
            'late_threshold_for_half_day_deduction': 1,
            'grace_period_minutes': 15,
        })
        return policy


class SalaryConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_config')
    monthly_base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    late_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Deduction per late check-in
    lop_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Deduction per LOP day (e.g. Base Salary / 30)
    max_permissions_per_month = models.IntegerField(default=2, help_text="Maximum permission requests allowed per month")
    max_hours_per_permission = models.DecimalField(max_digits=4, decimal_places=2, default=2.00, help_text="Maximum hours allowed per permission request")

    def __str__(self):
        return f"{self.user.username} - Base: {self.monthly_base_salary}"


class MonthlyPayroll(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('paid', 'Paid'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payrolls')
    month = models.IntegerField() # 1-12
    year = models.IntegerField()
    present_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal('0.0'))
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal('0.0'))
    late_days = models.IntegerField(default=0)
    approved_leaves = models.IntegerField(default=0)
    unapproved_leaves = models.IntegerField(default=0)
    
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # LOP and Late mark cuts
    net_salary = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    processed_at = models.DateTimeField(auto_now_add=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='processed_payrolls')

    class Meta:
        unique_together = ('user', 'month', 'year')
        ordering = ['-year', '-month']

    @property
    def late_deduction_amount(self):
        return Decimal('0.00')

    @property
    def lop_days(self):
        import calendar
        days_in_month = calendar.monthrange(self.year, self.month)[1] if (self.year and self.month) else 31
        unworked = float(days_in_month) - float(self.present_days or 0)
        allowed = float(getattr(self.user, 'monthly_off_count', 4))
        return max(0.0, unworked - allowed)

    @property
    def lop_deduction_amount(self):
        import calendar
        from decimal import Decimal
        days_in_month = calendar.monthrange(self.year, self.month)[1] if (self.year and self.month) else 31
        per_day_rate = self.base_salary / Decimal(str(days_in_month)) if days_in_month > 0 else Decimal('0')
        return (Decimal(str(self.lop_days)) * per_day_rate).quantize(Decimal('0.01'))

    @property
    def payable_days(self):
        import calendar
        days_in_month = calendar.monthrange(self.year, self.month)[1] if (self.year and self.month) else 31
        return max(0.0, float(days_in_month) - float(self.lop_days or 0))

    @property
    def total_days_in_month(self):
        import calendar
        if self.year and self.month:
            return calendar.monthrange(self.year, self.month)[1]
        return 31

    def __str__(self):
        return f"{self.user.username} - {self.month}/{self.year} - Net: {self.net_salary} ({self.status})"
