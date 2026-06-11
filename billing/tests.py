from django.test import TestCase
from decimal import Decimal
from core.models import Product, Branch, ComboPrice, ProductRegistry, ComboGroup, ComboTier
from billing.models import Bill, BillItem
from django.contrib.auth import get_user_model

User = get_user_model()

class ComboPricingTestCase(TestCase):
    def setUp(self):
        # Create user and branch
        self.user = User.objects.create_user(username='teststaff', password='password123', role='staff')
        self.branch = Branch.objects.create(name='Test Branch', location='Test Location', invoice_prefix='TB')
        self.user.branches.add(self.branch)
        self.user.active_branch = self.branch
        self.user.save()

        # Create product
        self.product = Product.objects.create(name='Test Apple', barcode='112233', price=500, branch=self.branch)
        
        # Register product to branch
        self.registry = ProductRegistry.objects.create(
            branch=self.branch,
            product=self.product,
            stock_quantity=100,
            low_stock_threshold=10
        )

        # Create combo prices
        # 3 items for ₹1300 (saving 200)
        # 5 items for ₹2000 (saving 500)
        self.combo3 = ComboPrice.objects.create(product=self.product, quantity=3, price=1300)
        self.combo5 = ComboPrice.objects.create(product=self.product, quantity=5, price=2000)

    def test_bill_item_savings_no_combo(self):
        # Create a bill
        bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=500
        )
        # Create bill item for 1 quantity (no combo matches, base price is 500)
        item = BillItem.objects.create(
            bill=bill,
            product=self.product,
            quantity=1,
            unit_price=500,
            subtotal=500
        )
        # Check savings
        self.assertEqual(item.regular_total, Decimal('500'))
        self.assertEqual(item.savings, Decimal('0'))
        self.assertEqual(bill.item_savings, Decimal('0'))
        self.assertEqual(bill.total_savings, Decimal('0'))

    def test_bill_item_savings_with_combos(self):
        # Quantity 3 -> Should cost 1300. Regular total is 1500. Saving should be 200.
        bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=1300
        )
        item = BillItem.objects.create(
            bill=bill,
            product=self.product,
            quantity=3,
            unit_price=433,  # 1300 / 3 rounded
            subtotal=1300
        )
        self.assertEqual(item.regular_total, Decimal('1500'))
        self.assertEqual(item.savings, Decimal('200'))
        self.assertEqual(bill.item_savings, Decimal('200'))
        self.assertEqual(bill.total_savings, Decimal('200'))

    def test_bill_item_savings_with_combos_and_remainders(self):
        # Quantity 8 -> 1 combo of 5 (₹2000) + 1 combo of 3 (₹1300) = ₹3300.
        # Regular total is 8 * 500 = 4000. Saving should be 700.
        bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=3300
        )
        item = BillItem.objects.create(
            bill=bill,
            product=self.product,
            quantity=8,
            unit_price=413,  # 3300 / 8 rounded
            subtotal=3300
        )
        self.assertEqual(item.regular_total, Decimal('4000'))
        self.assertEqual(item.savings, Decimal('700'))
        self.assertEqual(bill.item_savings, Decimal('700'))
        self.assertEqual(bill.total_savings, Decimal('700'))

    def test_bill_item_savings_with_retail_price(self):
        # Quantity 3 (₹1300) + ₹100 retail price adjustment
        bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=1400,
            retail_price=100
        )
        item = BillItem.objects.create(
            bill=bill,
            product=self.product,
            quantity=3,
            unit_price=433,
            subtotal=1300
        )
        self.assertEqual(item.regular_total, Decimal('1500'))
        self.assertEqual(item.savings, Decimal('200'))
        self.assertEqual(bill.item_savings, Decimal('200'))
        # Total savings = item savings (200) only, retail price is addition
        self.assertEqual(bill.total_savings, Decimal('200'))

    def test_bill_item_exchange_from_model(self):
        # Create a bill
        bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=500
        )
        item = BillItem.objects.create(
            bill=bill,
            product=self.product,
            quantity=1,
            unit_price=500,
            subtotal=500,
            exchange_from="Old Item Barcode"
        )
        self.assertEqual(item.exchange_from, "Old Item Barcode")


class MultiProductComboTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='teststaff2', password='password123', role='staff')
        self.branch = Branch.objects.create(name='Test Branch 2', location='Test Location 2', invoice_prefix='TB2')
        self.user.branches.add(self.branch)
        self.user.active_branch = self.branch
        self.user.save()

        # Create products
        self.p1 = Product.objects.create(name='Apple', barcode='101', price=100, branch=self.branch)
        self.p2 = Product.objects.create(name='Banana', barcode='102', price=150, branch=self.branch)
        
        # Register products
        ProductRegistry.objects.create(branch=self.branch, product=self.p1, stock_quantity=100)
        ProductRegistry.objects.create(branch=self.branch, product=self.p2, stock_quantity=100)

        # Create Combo Group
        self.group = ComboGroup.objects.create(name='Mix & Match Summer Promo', is_active=True)
        self.group.branches.add(self.branch)
        self.group.products.add(self.p1, self.p2)

        # Create Combo Tiers
        # 2 items for ₹180 (regular would be 200/250/300)
        # 5 items for ₹400
        ComboTier.objects.create(combo_group=self.group, quantity=2, price=180)
        ComboTier.objects.create(combo_group=self.group, quantity=5, price=400)

    def test_process_bill_with_combo_group(self):
        from django.urls import reverse
        import json
        self.client.force_login(self.user)

        # Let's add 3 of p1 and 3 of p2 (total 6 items)
        # Expanded prices: 150, 150, 150, 100, 100, 100
        # Optimal cost: 5-Combo (400) + 1 single item (p1: 100) = 500
        # Regular total: 3 * 100 + 3 * 150 = 750
        # Savings: 250
        payload = {
            'items': [
                {'id': self.p1.id, 'quantity': 3},
                {'id': self.p2.id, 'quantity': 3}
            ],
            'customer_name': 'Jane Doe',
            'customer_phone': '1234567890',
            'payment_method': 'cash'
        }

        response = self.client.post(
            reverse('process_bill'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        bill = Bill.objects.get(id=data['bill_id'])
        self.assertEqual(bill.total_amount, Decimal('500'))
        self.assertEqual(bill.total_savings, Decimal('250'))
