from django.db import migrations
import re

def fix_employee_ids(apps, schema_editor):
    User = apps.get_model('users', 'User')
    
    # Identify any user with an invalid employee_id pattern
    pattern = re.compile(r'^AR\d{4}$')
    
    # Order by id to ensure deterministic sequence assignment
    all_users = list(User.objects.all().order_by('id'))
    
    users_to_fix = []
    for user in all_users:
        if not user.employee_id or not pattern.match(user.employee_id):
            users_to_fix.append(user)
            
    # For each user that needs a fix, generate a correct employee_id
    for user in users_to_fix:
        prefix = "AR"
        valid_ids = [u.employee_id for u in User.objects.all() if u.employee_id and pattern.match(u.employee_id)]
        
        next_seq = 1
        if valid_ids:
            seqs = []
            for eid in valid_ids:
                try:
                    seqs.append(int(eid[len(prefix):]))
                except ValueError:
                    pass
            if seqs:
                next_seq = max(seqs) + 1
                
        candidate = f"{prefix}{next_seq:04d}"
        while User.objects.filter(employee_id=candidate).exists() or candidate in [u.employee_id for u in users_to_fix if u.employee_id]:
            next_seq += 1
            candidate = f"{prefix}{next_seq:04d}"
            
        user.employee_id = candidate
        user.save()

def reverse_fix_employee_ids(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(fix_employee_ids, reverse_code=reverse_fix_employee_ids),
    ]
