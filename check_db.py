import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def check_tables():
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'inventory_%'")
        tables = cursor.fetchall()
        print(f"Found inventory tables: {tables}")
        
        if tables:
            for table_tuple in tables:
                table_name = table_tuple[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"Table {table_name} has {count} rows.")

if __name__ == "__main__":
    check_tables()
