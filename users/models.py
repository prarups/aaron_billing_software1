from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
import re

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
        ('staff', 'Staff'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='staff', db_index=True)
    # Managers and Staff can be assigned to multiple branches
    branches = models.ManyToManyField('core.Branch', blank=True, related_name='assigned_users')
    # The branch currently selected for the session
    active_branch = models.ForeignKey('core.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_users')
    employee_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    has_product_rights = models.BooleanField(default=False)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def is_owner(self):
        return self.role == 'owner'

    def is_manager(self):
        return self.role == 'manager'

    def is_staff_role(self):
        return self.role == 'staff'

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


