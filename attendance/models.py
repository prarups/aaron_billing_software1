from django.db import models
from django.conf import settings

class Attendance(models.Model):
    STATUS_CHOICES = (
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('on_leave', 'On Leave'),
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

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"


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


class SalaryConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_config')
    monthly_base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    late_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Deduction per late check-in
    lop_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Deduction per LOP day (e.g. Base Salary / 30)

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
    present_days = models.IntegerField(default=0)
    absent_days = models.IntegerField(default=0)
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
    def late_deductions(self):
        try:
            return self.late_days * self.user.salary_config.late_deduction_amount
        except Exception:
            return 0.00

    @property
    def lop_days(self):
        return self.unapproved_leaves

    @property
    def lop_deductions(self):
        try:
            lop_days_to_deduct = max(0, self.unapproved_leaves - 4)
            return lop_days_to_deduct * self.user.salary_config.lop_deduction_amount
        except Exception:
            return 0.00

    def __str__(self):
        return f"{self.user.username} - {self.month}/{self.year} - Net: {self.net_salary} ({self.status})"
