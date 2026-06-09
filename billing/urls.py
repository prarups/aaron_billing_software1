from django.urls import path
from . import views, return_views

urlpatterns = [
    path('', views.pos_index, name='pos_index'),
    path('get-product/', views.get_product_by_barcode, name='get_product_by_barcode'),
    path('process-bill/', views.process_bill, name='process_bill'),
    path('bill/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('bill/<int:bill_id>/update-customer/', views.update_customer_details, name='update_customer_details'),
    path('bill/<int:bill_id>/edit-back/', views.edit_bill_back, name='edit_bill_back'),
    path('share/<uuid:share_id>/', views.public_bill_detail, name='public_bill_detail'),
    path('activity/', views.staff_activity, name='staff_activity'),
    path('all-bills/', views.owner_bill_list, name='owner_bill_list'),
    path('export/', views.export_sales_csv, name='export_sales_csv'),
    path('clear-exchange-session/', views.clear_exchange_session, name='clear_exchange_session'),
    path('return/', return_views.return_create_view, name='return_create'),
    path('return/bill-items/', return_views.get_bill_items_api, name='get_bill_items'),
]
