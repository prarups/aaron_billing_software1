from django.conf import settings
from django.db import models

class StaffAudit(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('branch_assign', 'Branch Assignment'),
        ('activate', 'Activate/Deactivate'),
    ]
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_entries',
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='performed_audits',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Staff Audit'
        verbose_name_plural = 'Staff Audits'
