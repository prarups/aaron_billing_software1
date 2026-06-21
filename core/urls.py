from django.urls import path
from . import views
from . import combo_views

urlpatterns = [
    path('products/', views.product_list, name='product_list'),
    path('products/export/', views.export_products_csv, name='export_products_csv'),
    path('products/add/', views.product_create, name='product_create'),
    path('products/edit/<int:pk>/', views.product_update, name='product_update'),
    path('products/update-price-ajax/<int:pk>/', views.update_product_price_ajax, name='update_product_price_ajax'),
    path('products/update-stock-ajax/<int:pk>/', views.update_product_stock_ajax, name='update_product_stock_ajax'),
    path('products/bulk-insert/', views.bulk_insert, name='bulk_insert'),
    path('products/bulk-template/', views.download_bulk_template, name='download_bulk_template'),
    path('products/adjust-stock/<int:reg_id>/', views.stock_adjustment, name='stock_adjustment'),
    path('products/adjust-stock/<int:reg_id>/history/', views.view_stock_adjustments, name='view_stock_adjustments'),
    path('reports/stock-pivot/', views.stock_pivot_report, name='stock_pivot_report'),
    path('reports/stock-pivot/export/', views.export_stock_pivot_excel, name='export_stock_pivot_excel'),
    path('pos/', views.pos_view, name='pos_view'),
    
    # Combo URLs
    path('combos/', combo_views.combo_list, name='combo_list'),
    path('combos/add/', combo_views.combo_create, name='combo_create'),
    path('combos/edit/<int:pk>/', combo_views.combo_edit, name='combo_edit'),
    path('combos/delete/<int:pk>/', combo_views.combo_delete, name='combo_delete'),
    path('combos/ajax-data/', combo_views.get_branch_combo_data, name='ajax_combo_data'),
    path('combos/branch-products-ajax/', combo_views.branch_products_ajax, name='branch_products_ajax'),
]
