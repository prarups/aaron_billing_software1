import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db.models import Sum, Q
from core.models import Product, Branch, ProductRegistry, StockTransaction

print("COMPARING STOCK CALCULATIONS FOR ALL PRODUCTS:\n")

for registry in ProductRegistry.objects.all().select_related('product', 'branch'):
    p = registry.product
    b = registry.branch
    curr_stock = registry.stock_quantity
    
    # All-time txns
    a_tx = StockTransaction.objects.filter(product=p, branch=b).aggregate(
        out_gross=Sum('quantity', filter=Q(transaction_type='OUT')),
        ret_good=Sum('quantity', filter=Q(transaction_type='IN') & Q(reference__startswith='Return #')),
        ret_dmg=Sum('quantity', filter=Q(transaction_type='DMG') & Q(reference__startswith='Return #')),
        dmg_std=Sum('quantity', filter=Q(transaction_type='DMG') & ~Q(reference__startswith='Return #')),
        adj=Sum('quantity', filter=Q(transaction_type='ADJ')),
    )
    
    out_gross = a_tx['out_gross'] or 0
    ret_good = a_tx['ret_good'] or 0
    ret_dmg = a_tx['ret_dmg'] or 0
    dmg_std = a_tx['dmg_std'] or 0
    adj = a_tx['adj'] or 0
    
    rec_old = curr_stock + out_gross + dmg_std - adj
    rec_new = curr_stock + out_gross + dmg_std - ret_good - adj
    rec_net_out = curr_stock + (out_gross - ret_good - ret_dmg) + dmg_std - adj
    rec_no_ret = curr_stock + (out_gross - ret_good - ret_dmg) + (dmg_std) - adj
    
    if ret_good > 0 or ret_dmg > 0:
        print(f"Product: {p.name} ({p.barcode}) | Branch: {b.name}")
        print(f"  Current Stock: {curr_stock} | Damaged Stock: {registry.damaged_qty}")
        print(f"  Gross Out: {out_gross} | Good Return: {ret_good} | Damaged Return: {ret_dmg} | Standard Dmg: {dmg_std} | Adj: {adj}")
        print(f"  Rec (old formula: curr + out_gross + dmg_std - adj) = {rec_old}")
        print(f"  Rec (new formula: curr + out_gross + dmg_std - ret_good - adj) = {rec_new}")
        print(f"  Rec (net out formula: curr + out_net + dmg_std - adj) = {rec_net_out}")
        print(f"  Rec (no ret: curr + out_net + dmg_total - adj) = {rec_no_ret}")
        print("-" * 50)
