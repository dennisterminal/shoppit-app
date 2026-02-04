# shoppit/urls.py
from django.contrib import admin
from django.urls import path
from shop_app import views
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # Product & cart
    path("products", views.products, name="product_list"),
    path("product_detail/<slug:slug>", views.product_detail, name="product_detail"),
    path("add_item/", views.add_item, name="add_item"),
    path("product_in_cart/", views.product_in_cart, name="product_in_cart"),
    path("get_cart_stat/", views.get_cart_stat, name="get_cart_stat"),
    path("get_cart/", views.get_cart, name="get_cart"),
    path("update_quantity/", views.update_quantity, name="update_quantity"),
    path("delete_cartitem/", views.delete_cartitem, name="delete_cartitem"),
    path("get_username/", views.get_username, name="get_username"),
    path("user_info/", views.user_info, name="user_info"),

    # ──────────────────────────────────────────────────────────────
    # PAYMENT ENDPOINTS – cleaned up
    # ──────────────────────────────────────────────────────────────
    path("initiate_payment/", views.initiate_flutterwave_payment, name="initiate_flutterwave"),   # ← Flutterwave (for the button that redirects)
    path("initiate-paypal-payment/", views.initiate_payment, name="initiate_paypal"),            # ← PayPal order creation
    path("capture-paypal-payment/", views.capture_payment, name="capture_paypal_payment"),       # ← PayPal capture

    # JWT
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Optional callback (you already have it)
    path("payment_callback/", views.payment_callback, name="payment_callback"),
]