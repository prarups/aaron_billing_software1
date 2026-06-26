from django.test import TestCase
from decimal import Decimal
from core.models import Product, Branch, ComboPrice, ProductRegistry, ComboGroup, ComboTier
from billing.models import Bill, BillItem
from django.contrib.auth import get_user_model

User = get_user_model()

class ComboPricingTestCase(TestCase):
    def setUp(self):
        # Create user and branch
        self.user = User.objects.create_user(username='teststaff', password='password123', role='sales_staff')
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
        self.user = User.objects.create_user(username='teststaff2', password='password123', role='sales_staff')
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
        self.assertEqual(bill.total_amount, Decimal('480'))
        self.assertEqual(bill.total_savings, Decimal('270'))
        self.assertEqual(len(list(bill.applied_combos)), 1)
        self.assertEqual(list(bill.applied_combos)[0].combo_id, self.group.combo_id)

    def test_process_bill_with_overlapping_combo_groups_shared_barcode(self):
        from django.urls import reverse
        import json
        self.client.force_login(self.user)

        # Create product p3
        p3 = Product.objects.create(name='Orange', barcode='103', price=200, branch=self.branch)
        ProductRegistry.objects.create(branch=self.branch, product=p3, stock_quantity=100)

        # Combo C: p3 only, milestone 5 -> 700 (min milestone = 5)
        group_c = ComboGroup.objects.create(name='Combo C', is_active=True)
        group_c.branches.add(self.branch)
        group_c.products.add(p3)
        ComboTier.objects.create(combo_group=group_c, quantity=5, price=700)

        # Combo D: p3 only, milestone 3 -> 500 (min milestone = 3)
        group_d = ComboGroup.objects.create(name='Combo D', is_active=True)
        group_d.branches.add(self.branch)
        group_d.products.add(p3)
        ComboTier.objects.create(combo_group=group_d, quantity=3, price=500)

        # Scanned: 3 of p3.
        # If Combo C is evaluated first, eligible qty = 3. Since 3 < 5 (min milestone of C), Combo C must skip processing p3.
        # Then Combo D is evaluated. Eligible qty = 3. Since 3 >= 3 (min milestone of D), Combo D processes p3 and applies milestone price 500.
        payload = {
            'items': [
                {'id': p3.id, 'quantity': 3}
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

    def test_process_bill_with_optional_customer_details(self):
        from django.urls import reverse
        import json
        self.client.force_login(self.user)

        payload = {
            'items': [
                {'id': self.p1.id, 'quantity': 1}
            ],
            'customer_name': '',
            'customer_phone': '',
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
        self.assertEqual(bill.customer_name, '')
        self.assertEqual(bill.customer_phone, '')



class BillDetailNavigationTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Test Branch', location='Test Location', invoice_prefix='TB')
        self.staff_user = User.objects.create_user(username='teststaff', password='password123', role='sales_staff', active_branch=self.branch)
        self.staff_user.branches.add(self.branch)
        self.staff_user.save()

        self.owner_user = User.objects.create_user(username='testowner', password='password123', role='owner', active_branch=self.branch)
        self.owner_user.branches.add(self.branch)
        self.owner_user.save()

        self.bill = Bill.objects.create(
            branch=self.branch,
            staff=self.owner_user,
            customer_name='John Doe',
            payment_method='cash',
            total_amount=500
        )

    def test_bill_detail_close_button_as_owner(self):
        self.client.force_login(self.owner_user)
        from django.urls import reverse
        url = reverse('bill_detail', args=[self.bill.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Verify close X button falls back to owner_bill_list for owners
        self.assertContains(response, 'href="/billing/all-bills/"')
        # Verify Back to Sales Report button is present for owners
        self.assertContains(response, 'Back to Sales Report')

    def test_bill_detail_close_button_as_staff(self):
        self.client.force_login(self.staff_user)
        from django.urls import reverse
        url = reverse('bill_detail', args=[self.bill.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Verify close X button falls back to staff_activity for staff
        self.assertContains(response, 'href="/billing/activity/"')
        # Verify Back to Daily Sales Activity button is present for staff
        self.assertContains(response, 'Back to Daily Sales Activity')

    def test_bill_detail_whatsapp_link_with_instagram(self):
        self.bill.customer_phone = '9876543210'
        self.bill.save()
        self.client.force_login(self.owner_user)
        from django.urls import reverse
        url = reverse('bill_detail', args=[self.bill.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        wa_link = response.context['wa_link']
        self.assertIsNotNone(wa_link)
        self.assertIn("https://wa.me/919876543210", wa_link)
        import urllib.parse
        self.assertIn("Follow us on Instagram: https://www.instagram.com/aaron_garments?igsh=YWpkdWE0emkyZjNv", urllib.parse.unquote(wa_link))

    def test_public_bill_detail_whatsapp_group_link(self):
        from django.urls import reverse
        url = reverse('public_bill_detail', args=[self.bill.share_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://chat.whatsapp.com/CjsuRAf3g1EHUbzMVU4VpE')
    def test_bill_detail_return_button_conditional(self):
        self.client.force_login(self.owner_user)
        from django.urls import reverse
        # When from_pos is NOT set, the return button is visible
        url = reverse('bill_detail', args=[self.bill.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Return / Exchange Items')

        # When from_pos is set to 'true', the return button is hidden
        url_with_param = f"{url}?from_pos=true"
        response = self.client.get(url_with_param)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Return / Exchange Items')


class ExchangePolicyTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from core.models import Branch, Product, ProductRegistry, ComboGroup
        User = get_user_model()
        self.branch = Branch.objects.create(name="Return Branch", location="Loc", invoice_prefix="RTN")
        self.user = User.objects.create_user(username="retstaff", password="password123", role="sales_staff")
        self.user.branches.add(self.branch)
        self.user.active_branch = self.branch
        self.user.save()

        # Create Products
        self.product_normal = Product.objects.create(branch=self.branch, name="Normal Item", barcode="9999", price=500)
        self.product_normal_cheap = Product.objects.create(branch=self.branch, name="Cheap Normal Item", barcode="9991", price=300)
        self.product_normal_expensive = Product.objects.create(branch=self.branch, name="Expensive Normal Item", barcode="9992", price=600)
        
        self.product_combo1 = Product.objects.create(branch=self.branch, name="Combo Item 1", barcode="8881", price=1000)
        self.product_combo2 = Product.objects.create(branch=self.branch, name="Combo Item 2", barcode="8882", price=1000)
        self.product_other = Product.objects.create(branch=self.branch, name="Non-combo Item", barcode="8883", price=1000)

        # Registries
        ProductRegistry.objects.create(branch=self.branch, product=self.product_normal, stock_quantity=10)
        ProductRegistry.objects.create(branch=self.branch, product=self.product_normal_cheap, stock_quantity=10)
        ProductRegistry.objects.create(branch=self.branch, product=self.product_normal_expensive, stock_quantity=10)
        ProductRegistry.objects.create(branch=self.branch, product=self.product_combo1, stock_quantity=10)
        ProductRegistry.objects.create(branch=self.branch, product=self.product_combo2, stock_quantity=10)
        ProductRegistry.objects.create(branch=self.branch, product=self.product_other, stock_quantity=10)

        # Create ComboGroup
        self.combo_group = ComboGroup.objects.create(name="Summer Mix", is_active=True)
        self.combo_group.branches.add(self.branch)
        self.combo_group.products.add(self.product_combo1, self.product_combo2)
        ComboTier.objects.create(combo_group=self.combo_group, quantity=1, price=900)

        # Create a Bill
        self.bill = Bill.objects.create(
            branch=self.branch,
            staff=self.user,
            customer_name="Jane Doe",
            payment_method="cash",
            total_amount=1500
        )
        self.item_normal = BillItem.objects.create(
            bill=self.bill,
            product=self.product_normal,
            quantity=1,
            unit_price=500,
            subtotal=500
        )
        self.item_combo = BillItem.objects.create(
            bill=self.bill,
            product=self.product_combo1,
            quantity=1,
            unit_price=1000,
            subtotal=1000
        )

    def test_normal_item_exchange_validation(self):
        from billing.forms import ReturnCreateForm
        import json

        # Cheap exchange should fail validation
        data_cheap = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Too small',
            'return_items': json.dumps([{
                'id': self.item_normal.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_normal_cheap.id,
                'replacement_quantity': 1
            }])
        }
        form_cheap = ReturnCreateForm(data=data_cheap)
        self.assertFalse(form_cheap.is_valid())

        # Equal price exchange should pass validation
        data_equal = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Too small',
            'return_items': json.dumps([{
                'id': self.item_normal.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_normal.id,
                'replacement_quantity': 1
            }])
        }
        form_equal = ReturnCreateForm(data=data_equal)
        self.assertTrue(form_equal.is_valid())

        # More expensive exchange should pass validation
        data_expensive = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Too small',
            'return_items': json.dumps([{
                'id': self.item_normal.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_normal_expensive.id,
                'replacement_quantity': 1
            }])
        }
        form_expensive = ReturnCreateForm(data=data_expensive)
        self.assertTrue(form_expensive.is_valid())

    def test_combo_item_exchange_validation(self):
        from billing.forms import ReturnCreateForm
        import json

        # Exchanging combo item for something outside combo group should fail validation
        data_invalid = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Wrong shade',
            'return_items': json.dumps([{
                'id': self.item_combo.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_other.id,
                'replacement_quantity': 1
            }])
        }
        form_invalid = ReturnCreateForm(data=data_invalid)
        self.assertFalse(form_invalid.is_valid())

        # Exchanging combo item for something inside combo group should pass validation
        data_valid = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Wrong shade',
            'return_items': json.dumps([{
                'id': self.item_combo.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_combo2.id,
                'replacement_quantity': 1
            }])
        }
        form_valid = ReturnCreateForm(data=data_valid)
        self.assertTrue(form_valid.is_valid())

    def test_exchange_stock_movements_and_fields(self):
        from billing.forms import ReturnCreateForm
        from core.models import ProductRegistry, StockTransaction
        import json

        # Process a good exchange
        data = {
            'invoice_id': self.bill.invoice_number,
            'reason': 'Fit issues',
            'return_items': json.dumps([{
                'id': self.item_normal.id,
                'quantity': 1,
                'condition': 'GOOD',
                'replacement_product_id': self.product_normal_expensive.id,
                'replacement_quantity': 1
            }])
        }
        form = ReturnCreateForm(data=data)
        self.assertTrue(form.is_valid())

        # Save return
        returns = form.save(self.user)
        self.assertEqual(len(returns), 1)
        ret = returns[0]

        # Verify ReturnRequest record
        self.assertEqual(ret.replacement_product, self.product_normal_expensive)
        self.assertEqual(ret.price_difference, 100) # 600 - 500 = 100

        # Verify Bill/BillItem fields
        self.item_normal.refresh_from_db()
        self.assertEqual(self.item_normal.returned_quantity, 1)
        self.bill.refresh_from_db()
        self.assertTrue(self.bill.has_returns)

        # Check stock registry updates:
        # Returned item (GOOD): stock should be +1 (10 -> 11)
        self.assertEqual(ProductRegistry.objects.get(branch=self.branch, product=self.product_normal).stock_quantity, 11)
        # Replacement item: stock should be -1 (10 -> 9)
        self.assertEqual(ProductRegistry.objects.get(branch=self.branch, product=self.product_normal_expensive).stock_quantity, 9)

        # Check Stock transactions logged:
        tx_in = StockTransaction.objects.filter(product=self.product_normal, transaction_type='IN')
        self.assertTrue(tx_in.exists())
        tx_out = StockTransaction.objects.filter(product=self.product_normal_expensive, transaction_type='OUT')
        self.assertTrue(tx_out.exists())
