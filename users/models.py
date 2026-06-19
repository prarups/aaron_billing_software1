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


class User(AbstractUser):
    ROLE_CHOICES = (
        ('owner', 'Admin'),
        ('manager', 'Manager'),
        ('assistant_manager', 'Assistant Manager'),
        ('sales_staff', 'Sales Staff'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='sales_staff', db_index=True)
    # Managers and Staff can be assigned to multiple branches
    branches = models.ManyToManyField('core.Branch', blank=True, related_name='assigned_users')
    # The branch currently selected for the session
    active_branch = models.ForeignKey('core.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_users')
    employee_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    date_of_joining = models.DateField(null=True, blank=True)
    has_product_rights = models.BooleanField(default=False)
    has_bill_edit_rights = models.BooleanField(default=False)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def is_owner(self):
        return self.role == 'owner'

    def is_manager(self):
        return self.role in ['manager', 'assistant_manager']

    def is_staff_role(self):
        return self.role == 'sales_staff'

    def get_accessible_branches(self):
        """Returns the branches this user is authorized to work in."""
        from core.models import Branch
        if self.is_owner():
            return Branch.objects.all()
        return self.branches.all()

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = generate_employee_id_for_user(self)
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


