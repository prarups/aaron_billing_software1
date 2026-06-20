from django.db import migrations

def apply_cascade_fk(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        return
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute("""
                ALTER TABLE "audit_staffaudit"
                DROP CONSTRAINT IF EXISTS "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id";
            """)
        except Exception:
            pass
        cursor.execute("""
            ALTER TABLE "audit_staffaudit"
            ADD CONSTRAINT "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id"
            FOREIGN KEY ("staff_id") REFERENCES "users_user" ("id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
        """)

def reverse_cascade_fk(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        return
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute("""
                ALTER TABLE "audit_staffaudit"
                DROP CONSTRAINT IF EXISTS "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id";
            """)
        except Exception:
            pass
        cursor.execute("""
            ALTER TABLE "audit_staffaudit"
            ADD CONSTRAINT "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id"
            FOREIGN KEY ("staff_id") REFERENCES "users_user" ("id") ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
        """)

class Migration(migrations.Migration):
    dependencies = [
        ('audit', '0003_alter_staffaudit_staff'),
    ]

    operations = [
        migrations.RunPython(apply_cascade_fk, reverse_cascade_fk),
    ]

