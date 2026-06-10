from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Product, Branch, ProductRegistry, StockTransaction

User = get_user_model()

class StockPivotReportTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Nellore Branch", code="10001", invoice_prefix="AN")
        self.user = User.objects.create_user(
            username="testowner", 
            password="password123", 
            role="owner",
            active_branch=self.branch
        )
        self.user.branches.add(self.branch)
        self.user.save()
        self.client.login(username="testowner", password="password123")

        self.product = Product.objects.create(name="jeans", barcode="610016", price=500)
        self.registry = ProductRegistry.objects.create(
            branch=self.branch,
            product=self.product,
            stock_quantity=88
        )

        # Create some historical/all-time stock transactions
        # Out (sales): 9
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='OUT',
            quantity=9,
            user=self.user
        )
        # Dmg: 2
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=2,
            user=self.user
        )
        # So current stock is 88. All-time OUT is 9. All-time DMG is 2.
        # Total received all-time should be: 88 + 9 + 2 = 99.

    def test_stock_pivot_report_view(self):
        # Create an ADJ transaction today of -5 items and reduce registry stock accordingly
        self.registry.stock_quantity = 83
        self.registry.save()
        
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='ADJ',
            quantity=-5,
            user=self.user
        )

        response = self.client.get(reverse('stock_pivot_report'))
        self.assertEqual(response.status_code, 200)
        
        report_data = response.context['report_data']
        self.assertEqual(len(report_data), 1)
        item = report_data[0]
        self.assertEqual(item['product'], self.product)
        self.assertEqual(item['total_rec'], 99)
        self.assertEqual(item['total_all_time_out'], 9)
        self.assertEqual(item['total_all_time_dmg'], 2)
        self.assertEqual(item['total_adj_plus'], 0)
        self.assertEqual(item['total_adj_minus'], 5)

        branch_stock = item['branch_stocks'][0]
        self.assertEqual(branch_stock['rec'], 99)
        self.assertEqual(branch_stock['all_time_out'], 9)
        self.assertEqual(branch_stock['all_time_dmg'], 2)
        self.assertEqual(branch_stock['adj_plus'], 0)
        self.assertEqual(branch_stock['adj_minus'], 5)

    def test_export_stock_pivot_excel(self):
        response = self.client.get(reverse('export_stock_pivot_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_product_update_stock_add(self):
        # Initial stock was 88
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'add',
            'stock_update_qty': '12',
            'stock_update_reason': 'Arrived today',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 100) # 88 + 12

        # Check transaction
        tx = StockTransaction.objects.filter(transaction_type='IN', reference__contains='Arrived today').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, 12)

    def test_product_update_stock_damage(self):
        # Initial stock was 88
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'damage',
            'stock_update_qty': '4',
            'stock_update_reason': 'Moth eaten',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 84) # 88 - 4

        # Check transaction
        tx = StockTransaction.objects.filter(transaction_type='DMG', reference__contains='Moth eaten').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, 4)

    def test_product_update_stock_correction(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()
        
        # Initial stock was 88
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correction',
            'stock_update_qty': '95',
            'stock_update_reason': 'Audit match',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 95)

        # Check transaction
        tx = StockTransaction.objects.filter(transaction_type='IN', reference__contains='Audit match').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, 7) # 95 - 88 = 7

    def test_product_update_stock_negative_correction(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Initial stock was 88
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correction',
            'stock_update_qty': '80',
            'stock_update_reason': 'Audit match negative',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 80)

        # Check transaction
        tx = StockTransaction.objects.filter(transaction_type='ADJ', reference__contains='Audit match negative').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, -8) # 80 - 88 = -8

    def test_product_update_stock_correction_with_today_in_txn(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Create an IN transaction today of 10 items
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='IN',
            quantity=10,
            user=self.user
        )
        # Initial stock was 88.
        # Now correct it down to 85 (diff is -3).
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correction',
            'stock_update_qty': '85',
            'stock_update_reason': 'Correct receipt typo',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 85)

        # The IN transaction today should have been reduced from 10 to 7!
        tx = StockTransaction.objects.filter(transaction_type='IN').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, 7)

        # No ADJ transaction should be created because it was absorbed by the IN transaction
        adj_tx = StockTransaction.objects.filter(transaction_type='ADJ').first()
        self.assertIsNone(adj_tx)

    def test_product_update_stock_correction_of_wrong_damage(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Create a DMG transaction today of 5 items
        # Let's say stock went from 88 to 83.
        self.registry.stock_quantity = 83
        self.registry.save()
        
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=5,
            user=self.user
        )

        # Now correct stock back to 85 (diff is +2).
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correction',
            'stock_update_qty': '85',
            'stock_update_reason': 'Correct wrong damage entry',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 85)

        # Today's DMG transaction should have been reduced from 5 to 3!
        tx = StockTransaction.objects.filter(transaction_type='DMG', reference__contains='Correct wrong damage entry').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.quantity, 3)

        # No IN or ADJ transaction should be created because it was absorbed by the DMG correction
        in_tx = StockTransaction.objects.filter(transaction_type='IN', reference__contains='Correct wrong damage entry').first()
        self.assertIsNone(in_tx)
        adj_tx = StockTransaction.objects.filter(transaction_type='ADJ', reference__contains='Correct wrong damage entry').first()
        self.assertIsNone(adj_tx)

    def test_product_update_stock_correct_damage_increase(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Initial stock was 88. Let's add 2 DMG transactions previously.
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=2,
            user=self.user
        )
        self.registry.stock_quantity = 88
        self.registry.damaged_qty = 2
        self.registry.save()

        # We set new damaged total to 5 (increase damage by 3).
        # Sellable stock should decrease by 3 (from 88 to 85).
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correct_damage',
            'stock_update_qty': '5',
            'stock_update_reason': 'More damages found',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 85)
        self.assertEqual(self.registry.damaged_qty, 5)

        # There should be DMG transaction with quantity = 3 (or today's dmg transaction modified to sum to 5)
        from django.db.models import Sum
        dmg_sum = StockTransaction.objects.filter(product=self.product, branch=self.branch, transaction_type='DMG').aggregate(t=Sum('quantity'))['t']
        self.assertEqual(dmg_sum, 5)

    def test_product_update_stock_correct_damage_decrease_with_today_dmg_txn(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Create DMG transaction today of 5 items
        self.registry.stock_quantity = 83
        self.registry.damaged_qty = 5
        self.registry.save()
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=5,
            user=self.user
        )

        # Set new damaged total to 3 (decrease damage by 2).
        # Sellable stock should increase by 2 (from 83 to 85).
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correct_damage',
            'stock_update_qty': '3',
            'stock_update_reason': 'Fewer damages actual',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 85)
        self.assertEqual(self.registry.damaged_qty, 3)

        # Today's DMG transaction should have been reduced to 3
        tx = StockTransaction.objects.filter(transaction_type='DMG').first()
        self.assertEqual(tx.quantity, 3)

    def test_product_update_stock_correct_damage_decrease_no_today_dmg_txn(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Setup historic DMG transactions (e.g. from yesterday)
        import datetime
        from django.utils import timezone
        yesterday = timezone.now() - datetime.timedelta(days=1)
        
        tx = StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=5,
            user=self.user
        )
        # Manually force created_at to yesterday
        StockTransaction.objects.filter(pk=tx.pk).update(created_at=yesterday)

        self.registry.stock_quantity = 83
        self.registry.damaged_qty = 5
        self.registry.save()

        # Set new damaged total to 3 (decrease damage by 2).
        # Sellable stock should increase by 2 (from 83 to 85).
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correct_damage',
            'stock_update_qty': '3',
            'stock_update_reason': 'Historic damage correction',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 85)
        self.assertEqual(self.registry.damaged_qty, 3)

        # A new DMG transaction with quantity -2 should have been logged
        new_tx = StockTransaction.objects.filter(transaction_type='DMG', quantity=-2).first()
        self.assertIsNotNone(new_tx)

    def test_product_update_stock_correct_damage_negative_stock_error(self):
        # Clear existing transactions to prevent interference
        StockTransaction.objects.all().delete()

        # Setup 2 sellable, 1 damaged
        self.registry.stock_quantity = 2
        self.registry.damaged_qty = 1
        self.registry.save()
        StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='DMG',
            quantity=1,
            user=self.user
        )

        # Correct total damage to 5 (needs 4 more units, but only 2 sellable exist).
        # This should fail with validation error and not redirect.
        url = reverse('product_update', args=[self.product.pk]) + f"?reg_id={self.registry.pk}"
        post_data = {
            'name': 'jeans',
            'barcode': '610016',
            'price': '500',
            'low_stock_threshold': '10',
            'stock_update_type': 'correct_damage',
            'stock_update_qty': '5',
            'stock_update_reason': 'Invalid damage count',
            'combos-TOTAL_FORMS': '0',
            'combos-INITIAL_FORMS': '0',
            'combos-MIN_NUM_FORMS': '0',
            'combos-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200) # Form page returned with errors

        self.registry.refresh_from_db()
        self.assertEqual(self.registry.stock_quantity, 2)
        self.assertEqual(self.registry.damaged_qty, 1)

    def test_stock_transaction_and_adjustment_truncation(self):
        # Create a transaction with a very long reference (> 100 characters)
        long_ref = "A" * 150
        tx = StockTransaction.objects.create(
            product=self.product,
            branch=self.branch,
            transaction_type='IN',
            quantity=10,
            reference=long_ref,
            user=self.user
        )
        self.assertEqual(len(tx.reference), 100)
        self.assertEqual(tx.reference, "A" * 100)

        # Create an adjustment with a very long reason (> 255 characters)
        from core.models import StockAdjustment
        long_reason = "B" * 300
        adj = StockAdjustment.objects.create(
            product=self.product,
            branch=self.branch,
            opening_balance=10,
            stock_in=0,
            stock_out=0,
            correction_amount=5,
            closing_stock=15,
            is_in_stock=True,
            reason=long_reason,
            user=self.user
        )
        self.assertEqual(len(adj.reason), 255)
        self.assertEqual(adj.reason, "B" * 255)

    def test_stock_pivot_report_view_excludes_adjustment_columns(self):
        # Verify that adjustment columns are removed visually from HTML,
        # but the View Corrected Details link exists for the branch breakdown.
        response = self.client.get(reverse('stock_pivot_report'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        
        # Verify columns '+ Adj' and '- Adj' are not in headers
        self.assertNotIn('+ Adj', html)
        self.assertNotIn('- Adj', html)

        # Verify the "View Corrected Details" button links to our new route
        history_url = reverse('view_stock_adjustments', args=[self.registry.pk])
        self.assertIn(history_url, html)
        self.assertIn('View Corrected Details', html)

    def test_view_stock_adjustments_history_view_access(self):
        # Create an adjustment
        from core.models import StockAdjustment
        adj = StockAdjustment.objects.create(
            product=self.product,
            branch=self.branch,
            opening_balance=88,
            stock_in=0,
            stock_out=0,
            correction_amount=10,
            closing_stock=98,
            is_in_stock=True,
            reason="Test manual fix",
            user=self.user
        )

        history_url = reverse('view_stock_adjustments', args=[self.registry.pk])
        
        # 1. Owner/Manager (self.user) gets access and sees the adjustment
        response = self.client.get(history_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test manual fix")
        self.assertContains(response, "+10")
        
        # 2. Staff user is blocked (redirected)
        staff_user = User.objects.create_user(
            username="teststaff", 
            password="password123", 
            role="staff",
            active_branch=self.branch
        )
        self.client.force_login(staff_user)
        response = self.client.get(history_url)
        self.assertEqual(response.status_code, 302) # Redirect to dashboard
        
        # 3. User without branch access is blocked
        other_branch = Branch.objects.create(name="Tirupati Branch", code="10002", invoice_prefix="TP")
        other_manager = User.objects.create_user(
            username="othermanager", 
            password="password123", 
            role="manager",
            active_branch=other_branch
        )
        other_manager.branches.add(other_branch)
        other_manager.save()
        
        self.client.force_login(other_manager)
        response = self.client.get(history_url)
        self.assertRedirects(response, reverse('stock_pivot_report'))


class BulkInsertTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Nellore Branch", code="10001", invoice_prefix="AN")
        self.user = User.objects.create_user(
            username="testowner", 
            password="password123", 
            role="owner",
            active_branch=self.branch
        )
        self.user.branches.add(self.branch)
        self.user.save()
        self.client.login(username="testowner", password="password123")

    def test_bulk_insert_success(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,15,5\n"
            "Jeans,JEANS01,500.00,L,10001,20,10\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)

        # Check product registry is created
        product = Product.objects.get(barcode="TSHIRT01")
        reg = ProductRegistry.objects.get(product=product, branch=self.branch)
        self.assertEqual(reg.stock_quantity, 15)

        product2 = Product.objects.get(barcode="JEANS01")
        reg2 = ProductRegistry.objects.get(product=product2, branch=self.branch)
        self.assertEqual(reg2.stock_quantity, 20)

    def test_bulk_insert_missing_mandatory_fields(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Missing Product Name
        csv_content1 = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            ",TSHIRT01,250.00,M,10001,15,5\n"
        )
        csv_file1 = SimpleUploadedFile("bulk1.csv", csv_content1.encode("utf-8"), content_type="text/csv")
        response1 = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file1})
        self.assertEqual(response1.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

        # Missing Initial Stock
        csv_content2 = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,,5\n"
        )
        csv_file2 = SimpleUploadedFile("bulk2.csv", csv_content2.encode("utf-8"), content_type="text/csv")
        response2 = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file2})
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

    def test_bulk_insert_duplicate_barcode_in_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,15,5\n"
            "Another T-Shirt,TSHIRT01,300.00,L,10001,10,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

    def test_bulk_insert_duplicate_name_in_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,15,5\n"
            "T-Shirt,TSHIRT02,300.00,L,10001,10,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())
        self.assertFalse(Product.objects.filter(barcode="TSHIRT02").exists())

    def test_bulk_insert_duplicate_barcode_in_database(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Pre-create a product and register it for the branch
        product = Product.objects.create(name="T-Shirt", barcode="TSHIRT01", price=250)
        ProductRegistry.objects.create(branch=self.branch, product=product, stock_quantity=10)
        
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,15,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        
        # Verify it wasn't modified or stock added, and the error was raised
        product.refresh_from_db()
        reg = ProductRegistry.objects.get(product=product, branch=self.branch)
        self.assertEqual(reg.stock_quantity, 10) # Unchanged

    def test_bulk_insert_duplicate_name_in_database(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Pre-create a product with same name but different barcode and register it for the branch
        product = Product.objects.create(name="T-Shirt", barcode="TSHIRT02", price=250)
        ProductRegistry.objects.create(branch=self.branch, product=product, stock_quantity=10)
        
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10001,15,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

    def test_bulk_insert_same_barcode_different_branch_allowed(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Create second branch
        other_branch = Branch.objects.create(name="Tirupati Branch", code="10002", invoice_prefix="TP")
        self.user.branches.add(other_branch)
        
        # Pre-create product and register for first branch (Nellore)
        product = Product.objects.create(name="T-Shirt", barcode="TSHIRT01", price=250)
        ProductRegistry.objects.create(branch=self.branch, product=product, stock_quantity=10)
        
        # Uploading same barcode and name for the second branch (Tirupati) should succeed
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,250.00,M,10002,15,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        
        # Verify it was successfully linked to the second branch
        reg_other = ProductRegistry.objects.get(product=product, branch=other_branch)
        self.assertEqual(reg_other.stock_quantity, 15)

    def test_bulk_insert_missing_price(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,,M,10001,15,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

    def test_bulk_insert_negative_price(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv_content = (
            "Name,Barcode,Price,Size,Branch Code,Initial Stock,Low Stock Alert\n"
            "T-Shirt,TSHIRT01,-15.50,M,10001,15,5\n"
        )
        csv_file = SimpleUploadedFile("bulk.csv", csv_content.encode("utf-8"), content_type="text/csv")
        response = self.client.post(reverse('bulk_insert'), {'csv_file': csv_file})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(barcode="TSHIRT01").exists())

    def test_bulk_insert_excel_success(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import openpyxl
        import io
        
        # Create an in-memory workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Barcode", "Price", "Size", "Branch Code", "Initial Stock", "Low Stock Alert"])
        # Use floating point numbers in Excel (e.g. 10001.0, 25.0) to test safety of conversions
        ws.append(["T-Shirt Excel", "EXCELTSHIRT01", 350.00, "M", 10001, 25, 5])
        ws.append(["Jeans Excel", "EXCELJEANS01", 600.00, "L", 10001.0, 30.0, 10.0])
        
        excel_io = io.BytesIO()
        wb.save(excel_io)
        excel_io.seek(0)
        
        excel_file = SimpleUploadedFile(
            "bulk.xlsx",
            excel_io.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        response = self.client.post(reverse('bulk_insert'), {'csv_file': excel_file})
        self.assertEqual(response.status_code, 200)
        
        # Check product registry is created
        product = Product.objects.get(barcode="EXCELTSHIRT01")
        reg = ProductRegistry.objects.get(product=product, branch=self.branch)
        self.assertEqual(reg.stock_quantity, 25)
        self.assertEqual(product.price, 350.00)
        
        product2 = Product.objects.get(barcode="EXCELJEANS01")
        reg2 = ProductRegistry.objects.get(product=product2, branch=self.branch)
        self.assertEqual(reg2.stock_quantity, 30)
        self.assertEqual(product2.price, 600.00)

    def test_bulk_insert_excel_validation_error(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import openpyxl
        import io
        
        # Missing Product Name on row 2
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Name", "Barcode", "Price", "Size", "Branch Code", "Initial Stock", "Low Stock Alert"])
        ws.append(["", "EXCELTSHIRT02", 350.00, "M", 10001, 25, 5])
        
        excel_io = io.BytesIO()
        wb.save(excel_io)
        excel_io.seek(0)
        
        excel_file = SimpleUploadedFile(
            "bulk_invalid.xlsx",
            excel_io.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        response = self.client.post(reverse('bulk_insert'), {'csv_file': excel_file})
        self.assertEqual(response.status_code, 200)
        
        # Ensure it was rolled back and product wasn't created
        self.assertFalse(Product.objects.filter(barcode="EXCELTSHIRT02").exists())







