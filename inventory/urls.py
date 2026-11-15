from django.urls import path
from . import views

urlpatterns = [
    path('transfers/', views.stock_transfer_list, name='stock_transfer_list'),
    path('transfers/create/', views.stock_transfer_create, name='stock_transfer_create'),
    path('transfers/template/', views.download_transfer_template, name='download_transfer_template'),
    path('transfers/<int:pk>/', views.stock_transfer_detail, name='stock_transfer_detail'),
    path('transfers/<int:pk>/edit/', views.stock_transfer_edit, name='stock_transfer_edit'),
    path('transfers/<int:pk>/rollback/', views.stock_transfer_rollback, name='stock_transfer_rollback'),
    path('transfers/ajax-stock/', views.ajax_product_branch_stock, name='ajax_product_branch_stock'),
]
