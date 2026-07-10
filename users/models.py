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
            self.code = slugify(self.name).replace('-', '_')
            
        super().save(*args, **kwargs)
        
        # Propagate changes to all users assigned to this role
        try:
            from django.apps import apps
            User = apps.get_model('users', 'User')
            User.objects.filter(role=self.code).update(
                has_pos_access=self.has_pos_access,
                has_attendance_access=self.has_attendance_access,
                has_product_rights=self.has_product_rights,
                has_bill_edit_rights=self.has_bill_edit_rights
            )
        except Exception:
            pass


class User(AbstractUser):
    ROLE_CHOICES = (
        ('owner', 'Admin'),
        ('regional_manager', 'Regional Manager'),
        ('manager', 'Manager'),
        ('assistant_manager', 'Assistant Manager'),
        ('sales_staff', 'Sales Staff'),
    )
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='sales_staff', db_index=True)
    # Managers and Staff can be assigned to multiple branches
    branches = models.ManyToManyField('core.Branch', blank=True, related_name='assigned_users')
    # The branch currently selected for the session
    active_branch = models.ForeignKey('core.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_users')
    employee_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    date_of_joining = models.DateField(null=True, blank=True)
    has_product_rights = models.BooleanField(default=False)
    has_bill_edit_rights = models.BooleanField(default=False)
    has_pos_access = models.BooleanField(default=True)
    has_attendance_access = models.BooleanField(default=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    shift_start_time = models.TimeField(default="09:00:00", help_text="Shift start time")
    shift_end_time = models.TimeField(default="17:00:00", help_text="Shift end time")
    grace_period_minutes = models.IntegerField(default=15, help_text="Grace period in minutes before marked Late")
    last_activity = models.DateTimeField(null=True, blank=True)


    @property
    def is_online(self):
        if self.last_activity:
            from django.utils import timezone
            return (timezone.now() - self.last_activity).total_seconds() < 300
        return False

    def is_owner(self):
        return self.role == 'owner'

    def is_manager(self):
        return self.role in ['manager', 'assistant_manager']

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

    def get_accessible_branches(self):
        """Returns the branches this user is authorized to work in."""
        from core.models import Branch
        if self.is_owner() or self.role == 'regional_manager':
            return Branch.objects.all()
        if self.role:
            try:
                crole = CustomRole.objects.get(code=self.role)
                if crole.has_all_branches_access:
                    return Branch.objects.all()
            except CustomRole.DoesNotExist:
                pass
        return self.branches.all()

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = generate_employee_id_for_user(self)
        
        # Shift fields defaults fallback
        if self.shift_start_time is None:
            self.shift_start_time = "09:00:00"
        if self.shift_end_time is None:
            self.shift_end_time = "17:00:00"
        if self.grace_period_minutes is None:
            self.grace_period_minutes = 15
        
        # Sync permissions if role is custom
        if self.role and self.role not in ['owner', 'regional_manager', 'manager', 'assistant_manager', 'sales_staff']:
            try:
                crole = CustomRole.objects.get(code=self.role)
                self.has_pos_access = crole.has_pos_access
                self.has_attendance_access = crole.has_attendance_access
                self.has_product_rights = crole.has_product_rights
                self.has_bill_edit_rights = crole.has_bill_edit_rights
            except CustomRole.DoesNotExist:
                pass
                
        super().save(*args, **kwargs)


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

@receiver(post_delete, sender=User)
def audit_user_delete(sender, instance, **kwargs):
    # Create audit entry without FK to the deleted user to avoid FK violation
    StaffAudit.objects.create(
        staff=None,
        performed_by=None,
        action="delete",
        details={"username": instance.username, "role": instance.role, "deleted_user_id": instance.id},
    )


