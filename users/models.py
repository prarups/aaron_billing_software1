from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
import re
from django.conf import settings

def generate_employee_id_for_user(user):
    prefix = "AR"
    from django.db.models import Max
    # Find the max sequence number for this prefix
    max_emp = User.objects.filter(employee_id__startswith=prefix).aggregate(Max('employee_id'))['employee_id__max']
    
    next_seq = 1
    if max_emp:
        try:
            # Extract the numeric suffix
            num_str = max_emp[len(prefix):]
            seq = int(num_str)
            next_seq = seq + 1
        except (ValueError, IndexError):
            pass
            
    candidate = f"{prefix}{next_seq:04d}"
    # Ensure uniqueness in case of race conditions or gaps
    while User.objects.filter(employee_id=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}"
        
    return candidate


class CustomRole(models.Model):
    name = models.CharField(max_length=50, unique=True)
    code = models.SlugField(max_length=50, unique=True, blank=True)
    
    dashboard_access = models.CharField(max_length=20, default='manager', help_text="Dashboard level: owner, manager, or staff")
    has_pos_access = models.BooleanField(default=True)
    has_attendance_access = models.BooleanField(default=True)
    has_all_branches_access = models.BooleanField(default=False)
    
    has_product_rights = models.BooleanField(default=False)
    has_bill_edit_rights = models.BooleanField(default=False)
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            from django.utils.text import slugify
            base_code = slugify(self.name).replace('-', '_')
            code = base_code
            seq = 1
            while CustomRole.objects.filter(code=code).exclude(pk=self.pk).exists():
                code = f"{base_code}_{seq}"
                seq += 1
            self.code = code
            
        super().save(*args, **kwargs)
        
        # Propagate changes to all users assigned to this role
        try:
            from django.apps import apps
            User = apps.get_model('users', 'User')
            User.objects.filter(role=self.code).update(
                has_pos_access=self.has_pos_access,
                has_attendance_access=self.has_attendance_access,
                has_product_rights=self.has_product_rights,
                has_bill_edit_rights=self.has_bill_edit_rights,
                dashboard_access=self.dashboard_access
            )
        except Exception:
            pass


class RoleShiftPolicy(models.Model):
    role = models.CharField(max_length=50, unique=True, db_index=True)
    role_name = models.CharField(max_length=100, blank=True)
    shift_start_time = models.TimeField(default="09:00:00")
    shift_end_time = models.TimeField(default="17:00:00")
    monthly_off_count = models.IntegerField(default=4, help_text="Number of monthly week-offs allowed for this role")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.role_name or self.role} Policy ({self.shift_start_time} - {self.shift_end_time}, {self.monthly_off_count} Offs/Month)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from django.apps import apps
            User = apps.get_model('users', 'User')
            Attendance = apps.get_model('attendance', 'Attendance')
            User.objects.filter(role=self.role).update(
                shift_start_time=self.shift_start_time,
                shift_end_time=self.shift_end_time,
                monthly_off_count=self.monthly_off_count
            )
            # Recalculate status for all attendance records belonging to users with this role
            for att in Attendance.objects.filter(user__role=self.role):
                att.recalculate_status()
                att.save()
        except Exception:
            pass

    @classmethod
    def get_policy_for_role(cls, role_code):
        policy = cls.objects.filter(role=role_code).first()
        if not policy:
            role_names = {
                'owner': 'Admin',
                'regional_manager': 'Regional Manager',
                'general_manager': 'General Manager',
                'manager': 'Manager',
                'assistant_manager': 'Assistant Manager',
                'sales_staff': 'Sales Staff',
            }
            name = role_names.get(role_code)
            if not name:
                try:
                    crole = CustomRole.objects.get(code=role_code)
                    name = crole.name
                except Exception:
                    name = role_code.replace('_', ' ').title()
            try:
                policy, _ = cls.objects.get_or_create(
                    role=role_code,
                    defaults={
                        'role_name': name,
                        'shift_start_time': "09:00:00",
                        'shift_end_time': "17:00:00",
                        'monthly_off_count': 4
                    }
                )
            except Exception:
                policy = cls.objects.filter(role=role_code).first()
        return policy


class User(AbstractUser):
    ROLE_CHOICES = (
        ('owner', 'Admin'),
        ('regional_manager', 'Regional Manager'),
        ('general_manager', 'General Manager'),
        ('manager', 'Manager'),
        ('assistant_manager', 'Assistant Manager'),
        ('sales_staff', 'Sales Staff'),
    )
    role = models.CharField(max_length=50, default='sales_staff', db_index=True)
    dashboard_access = models.CharField(max_length=20, default='staff', help_text="Dashboard level: owner, manager, or staff")
    # Managers and Staff can be assigned to multiple branches
    branches = models.ManyToManyField('core.Branch', blank=True, related_name='assigned_users')
    # The branch currently selected for the session
    active_branch = models.ForeignKey('core.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_users')
    employee_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    date_of_joining = models.DateField(null=True, blank=True)
    designation = models.CharField(max_length=100, blank=True, null=True, help_text="Job Designation")
    bank_name = models.CharField(max_length=100, blank=True, null=True, help_text="Bank Name")
    account_number = models.CharField(max_length=50, blank=True, null=True, help_text="Bank Account Number")
    ifsc_code = models.CharField(max_length=20, blank=True, null=True, help_text="Bank IFSC Code")
    has_product_rights = models.BooleanField(default=False)
    has_bill_edit_rights = models.BooleanField(default=False)
    has_pos_access = models.BooleanField(default=True)
    has_attendance_access = models.BooleanField(default=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    shift_start_time = models.TimeField(default="09:00:00", help_text="Shift start time")
    shift_end_time = models.TimeField(default="17:00:00", help_text="Shift end time")
    monthly_off_count = models.IntegerField(default=4, help_text="Monthly week offs count")
    grace_period_minutes = models.IntegerField(default=15, help_text="Grace period in minutes before marked Late")
    last_activity = models.DateTimeField(null=True, blank=True)


    @property
    def is_online(self):
        if self.last_activity:
            from django.utils import timezone
            return (timezone.now() - self.last_activity).total_seconds() < 300
        return False

    def is_owner(self):
        if self.is_superuser or self.role in ['owner', 'admin']:
            return True
        if self.dashboard_access == 'owner':
            return True
        if self.role:
            try:
                crole = CustomRole.objects.get(code=self.role)
                if crole.dashboard_access == 'owner':
                    return True
            except Exception:
                pass
        return False

    def is_manager(self):
        if self.is_owner():
            return True
        if self.role in ['general_manager', 'manager', 'assistant_manager', 'regional_manager']:
            return True
        if self.dashboard_access in ['owner', 'manager', 'regional_manager']:
            return True
        if self.role:
            try:
                crole = CustomRole.objects.get(code=self.role)
                if crole.dashboard_access in ['owner', 'manager', 'regional_manager'] or crole.has_all_branches_access or crole.has_product_rights or crole.has_bill_edit_rights:
                    return True
            except Exception:
                pass
            if any(term in self.role.lower() for term in ['manager', 'admin', 'head', 'lead', 'supervisor', 'general', 'audit']):
                return True
        return False

    def is_staff_role(self):
        return self.role == 'sales_staff'

    @property
    def role_display(self):
        choices_dict = dict(self.ROLE_CHOICES)
        if self.role in choices_dict:
            return choices_dict[self.role]
        try:
            return CustomRole.objects.get(code=self.role).name
        except Exception:
            return self.role.replace('_', ' ').title()

    def get_role_display(self):
        return self.role_display

    @property
    def has_all_branches(self):
        if self.is_superuser or self.role in ['owner', 'admin', 'regional_manager']:
            return True
        if self.role:
            try:
                crole = CustomRole.objects.get(code=self.role)
                return crole.has_all_branches_access
            except CustomRole.DoesNotExist:
                pass
        return False

    def get_accessible_branches(self):
        """Returns the branches this user is authorized to work in."""
        from core.models import Branch
        if self.is_superuser or self.has_all_branches:
            return Branch.objects.all()

        ub = self.branches.all()
        if ub.exists():
            return ub

        if self.active_branch:
            return Branch.objects.filter(id=self.active_branch.id)

        return Branch.objects.none()

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = generate_employee_id_for_user(self)
        
        # Shift fields & week-offs from Role policy
        if self.role:
            try:
                policy = RoleShiftPolicy.get_policy_for_role(self.role)
                self.shift_start_time = policy.shift_start_time
                self.shift_end_time = policy.shift_end_time
                self.monthly_off_count = policy.monthly_off_count
            except Exception:
                pass

        if self.shift_start_time is None:
            self.shift_start_time = "09:00:00"
        if self.shift_end_time is None:
            self.shift_end_time = "17:00:00"
        if self.grace_period_minutes is None:
            self.grace_period_minutes = 15

        # Sync permissions & dashboard access from CustomRole if exists
        if self.role:
            try:
                crole = CustomRole.objects.get(code=self.role)
                self.has_pos_access = crole.has_pos_access
                self.has_attendance_access = crole.has_attendance_access
                self.has_product_rights = crole.has_product_rights
                self.has_bill_edit_rights = crole.has_bill_edit_rights
                self.dashboard_access = crole.dashboard_access
            except CustomRole.DoesNotExist:
                if self.role == 'owner':
                    self.dashboard_access = 'owner'
                elif self.role in ['regional_manager', 'general_manager', 'manager', 'assistant_manager']:
                    self.dashboard_access = 'manager'
                elif self.role == 'sales_staff':
                    self.dashboard_access = 'staff'
                
        super().save(*args, **kwargs)
        if self.active_branch and not self.has_all_branches and not self.branches.filter(id=self.active_branch.id).exists():
            self.branches.add(self.active_branch)


@receiver(m2m_changed, sender=User.branches.through)
def user_branches_changed(sender, instance, action, **kwargs):
    if action == "post_add":
        if not instance.employee_id:
            instance.employee_id = generate_employee_id_for_user(instance)
            instance.save(update_fields=['employee_id'])

# Audit logging signals
from audit.models import StaffAudit
from django.db.models.signals import post_save, post_delete

@receiver(post_save, sender=User)
def audit_user_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    StaffAudit.objects.create(
        staff=instance,
        performed_by=None,
        action=action,
        details={
            "username": instance.username,
            "role": instance.role,
            "branches": list(instance.branches.values_list('id', flat=True)),
        },
    )

@receiver(post_delete, sender=CustomRole)
def custom_role_deleted(sender, instance, **kwargs):
    RoleShiftPolicy.objects.filter(role=instance.code).delete()

@receiver(post_delete, sender=User)
def audit_user_delete(sender, instance, **kwargs):
    # Create audit entry without FK to the deleted user to avoid FK violation
    StaffAudit.objects.create(
        staff=None,
        performed_by=None,
        action="delete",
        details={"username": instance.username, "role": instance.role, "deleted_user_id": instance.id},
    )


