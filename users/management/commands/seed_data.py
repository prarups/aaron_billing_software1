from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Branch, Product
from inventory.models import Inventory

User = get_user_model()

class Command(BaseCommand):
    help = 'Seed initial data for the billing system'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')

        # Create Owner
        if not User.objects.filter(username='owner').exists():
            owner = User.objects.create_superuser('owner', 'owner@example.com', 'password')
            owner.role = 'owner'
            owner.save()
            self.stdout.write('Created superuser: owner / password')

        # Create Branches
        branch1, _ = Branch.objects.get_or_create(name='Arron Kavali', location='Kavali, AP', contact_number='1234567890')
        branch2, _ = Branch.objects.get_or_create(name='Arron Nellore', location='Nellore, AP', contact_number='0987654321')
        self.stdout.write(f'Created branches: {branch1.name}, {branch2.name}')

        # Create Manager for Branch 1
        if not User.objects.filter(username='manager1').exists():
            manager = User.objects.create_user('manager1', 'manager1@example.com', 'password')
            manager.role = 'manager'
            manager.branch = branch1
            manager.save()
            self.stdout.write('Created manager: manager1 / password (assigned to Kavali)')

        # Create Staff for Branch 1
        if not User.objects.filter(username='staff1').exists():
            staff = User.objects.create_user('staff1', 'staff1@example.com', 'password')
            staff.role = 'staff'
            staff.branch = branch1
            staff.save()
            self.stdout.write('Created staff: staff1 / password (assigned to Kavali)')

        # Create some Products and Stock
        products_data = [
            {'name': 'White Cotton Shirt', 'barcode': '1001', 'price': 899.00},
            {'name': 'Blue Denim Jeans', 'barcode': '1002', 'price': 1499.00},
            {'name': 'Leather Belt', 'barcode': '1003', 'price': 499.00},
            {'name': 'Casual Sneakers', 'barcode': '1004', 'price': 2499.00},
        ]

        for p_data in products_data:
            product, _ = Product.objects.get_or_create(barcode=p_data['barcode'], defaults={'name': p_data['name'], 'price': p_data['price']})
            # Add to both branches
            Inventory.objects.get_or_create(branch=branch1, product=product, defaults={'stock_quantity': 50})
            Inventory.objects.get_or_create(branch=branch2, product=product, defaults={'stock_quantity': 30})

        self.stdout.write('Finished seeding products and inventory.')
