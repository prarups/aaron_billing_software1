from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('audit', '0003_alter_staffaudit_staff'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "audit_staffaudit"
                DROP CONSTRAINT IF EXISTS "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id";
                ALTER TABLE "audit_staffaudit"
                ADD CONSTRAINT "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id"
                FOREIGN KEY ("staff_id") REFERENCES "users_user" ("id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
            """,
            reverse_sql="""
                ALTER TABLE "audit_staffaudit"
                DROP CONSTRAINT IF EXISTS "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id";
                ALTER TABLE "audit_staffaudit"
                ADD CONSTRAINT "audit_staffaudit_staff_id_8bbbfd53_fk_users_user_id"
                FOREIGN KEY ("staff_id") REFERENCES "users_user" ("id") ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
            """,
        ),
    ]
