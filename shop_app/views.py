from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.conf import settings
from django.shortcuts import get_object_or_404
from decimal import Decimal
import uuid
import requests
import traceback
import paypalrestsdk

from .models import Cart, CartItem, Product, Transaction
from .serializers import (
    CartItemSerializer,
    UserSerializer,
    CartSerializer,
    ProductSerializer,
    ProductDetailSerializer,
    SimpleCartSerializer,
    CustomTokenObtainPairSerializer,
)

BASE_URL = settings.REACT_BASE_URL

paypalrestsdk.configure({
    "mode": settings.PAYPAL_MODE,
    "client_id": settings.PAYPAL_CLIENT_ID,
    "client_secret": settings.PAYPAL_CLIENT_SECRET
})


# ------------------ Product Views ------------------

@api_view(["GET"])
def products(request):
    products = Product.objects.all()
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    serializer = ProductDetailSerializer(product)
    return Response(serializer.data)


# ------------------ Cart Views ------------------

@api_view(["POST"])
def add_item(request):
    try:
        cart_code = request.data.get("cart_code")
        product_id = request.data.get("product_id")

        if not cart_code or not product_id:
            return Response({"error": "cart_code and product_id are required"}, status=400)

        cart, _ = Cart.objects.get_or_create(cart_code=cart_code)
        product = get_object_or_404(Product, id=product_id)

        cartitem, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if created:
            cartitem.quantity = 1
        else:
            cartitem.quantity += 1
        cartitem.save()

        serializer = CartItemSerializer(cartitem)
        return Response({"data": serializer.data, "message": "Item added to cart successfully"}, status=201)
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=400)


@api_view(["GET"])
def product_in_cart(request):
    cart_code = request.query_params.get("cart_code")
    product_id = request.query_params.get("product_id")

    if not cart_code or not product_id:
        return Response({"error": "cart_code and product_id are required"}, status=400)

    cart = get_object_or_404(Cart, cart_code=cart_code)
    product = get_object_or_404(Product, id=product_id)

    product_exists_in_cart = CartItem.objects.filter(cart=cart, product=product).exists()
    return Response({"product_in_cart": product_exists_in_cart})


@api_view(["GET"])
def get_cart_stat(request):
    cart_code = request.query_params.get("cart_code")
    if not cart_code:
        return Response({"error": "cart_code is required"}, status=400)

    cart = get_object_or_404(Cart, cart_code=cart_code, paid=False)
    serializer = SimpleCartSerializer(cart)
    return Response(serializer.data)

@api_view(["GET"])
def get_cart(request):
    cart_code = request.query_params.get("cart_code")
    if not cart_code:
        return Response({"error": "cart_code is required"}, status=400)

    try:
        cart = Cart.objects.get(cart_code=cart_code, paid=False)
        serializer = CartSerializer(cart)
        return Response(serializer.data)
    except Cart.DoesNotExist:
        # Return empty cart instead of 404
        return Response({
            "cart_code": cart_code,
            "paid": False,
            "items": [],
            "total": "0.00",
            "message": "Cart not found, returning empty cart"
        })


@api_view(["PATCH"])
def update_quantity(request):
    try:
        item_id = request.data.get("item_id")
        quantity = int(request.data.get("quantity", 1))

        if not item_id:
            return Response({"error": "item_id is required"}, status=400)
        if quantity < 1:
            return Response({"error": "Quantity must be at least 1"}, status=400)

        cart_item = get_object_or_404(CartItem, id=item_id)
        cart_item.quantity = quantity
        cart_item.save()
        serializer = CartItemSerializer(cart_item)
        return Response({"data": serializer.data, "message": "Cart item quantity updated successfully"})
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=400)


@api_view(["POST"])
def delete_cartitem(request):
    try:
        cartitem_id = request.data.get("item_id")
        if not cartitem_id:
            return Response({"error": "item_id is required"}, status=400)

        cartitem = get_object_or_404(CartItem, id=cartitem_id)
        cartitem.delete()
        return Response({"message": "Item deleted from cart successfully"}, status=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=400)


# ------------------ Auth & User Views ------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_username(request):
    return Response({"username": request.user.username})


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_info(request):
    user = request.user
    serializer = UserSerializer(user)
    return Response(serializer.data)


# ------------------ Payment Views ------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def initiate_flutterwave_payment(request):
    try:
        cart_code = request.data.get("cart_code")
        if not cart_code:
            return Response({"error": "cart_code is required"}, status=400)

        cart = get_object_or_404(Cart, cart_code=cart_code)

        amount = sum(item.quantity * item.product.price for item in cart.items.all())
        tax = Decimal("4.00")
        total_amount = amount + tax

        if total_amount <= 0:
            return Response({"error": "Cart total must be greater than 0"}, status=400)

        tx_ref = str(uuid.uuid4())

        Transaction.objects.create(
            ref=tx_ref,
            cart=cart,
            amount=total_amount,
            currency="KES",
            user=request.user,
            status="pending"
        )

        # ────── DEBUG PRINTS (remove later) ──────
        print("=== FLUTTERWAVE DEBUG START ===")
        print("User email:", request.user.email)
        print("Total amount:", total_amount)
        print("FLUTTERWAVE_SECRET_KEY exists?", bool(getattr(settings, "FLUTTERWAVE_SECRET_KEY", None)))
        print("BASE_URL used:", getattr(settings, "BASE_URL", "http://127.0.0.1:8000"))
        # ────────────────────────────────────────

        payload = {
            "tx_ref": tx_ref,
            "amount": str(total_amount.quantize(Decimal("0.00"))),
            "currency": "KES",
            "redirect_url": f"{settings.REACT_BASE_URL}/payment-status",   # ← comma added
            "customer": {
                "email": request.user.email or "test@example.com",
                "phonenumber": getattr(request.user, "phone", "0700000000"),
                "name": f"{request.user.first_name or ''} {request.user.last_name or ''}".strip() or "Customer"
            },
            "customizations": {
                "title": "Shoppit",
                "description": "Cart Payment"
            }
        }

        headers = {
            "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        print("Payload being sent:", payload)

        r = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers)
        print("Flutterwave status code:", r.status_code)
        print("Flutterwave raw response:", r.text)

        r.raise_for_status()
        data = r.json()

        return Response({
            "status": "success",
            "data": {"link": data["data"]["link"]}
        })

    except AttributeError as e:
        print("Missing Django setting:", e)
        return Response({"error": f"Missing setting: {e}"}, status=400)
    except requests.HTTPError as e:
        print("Flutterwave returned error:", e.response.text)
        return Response({"error": f"Flutterwave error: {e.response.text}"}, status=400)
    except Exception as e:
        traceback.print_exc()
        return Response({"error": str(e)}, status=400)


@api_view(['GET', 'POST'])          # ← changed from ['POST'] only (Flutterwave redirect uses GET)
def payment_callback(request):
    """
    Flutterwave redirects here after payment. 
    """
    status = request.GET.get("status") 
    tx_ref = request.GET.get("tx_ref") 
    transaction_id = request.GET.get("transaction_id")

    if status == 'successful':
        try:
            headers = {
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"
            }

            response = requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify", headers=headers)
            response_data = response.json()

            if response_data['status'] == 'success':
                transaction = Transaction.objects.get(ref=tx_ref)
                user = transaction.user

                if (response_data['data']['status'] == 'successful'
                    and float(response_data['data']['amount']) == float(transaction.amount)
                    and response_data['data']['currency'] == transaction.currency):
                    
                    transaction.status = 'completed'
                    transaction.save()

                    cart = transaction.cart
                    cart.paid = True
                    cart.user = user
                    cart.save()

                    CartItem.objects.filter(cart=cart).update(cart_paid=True)

                    return Response({
                        'message': 'Payment successful!', 
                        'subMessage': 'You have successfully made payment'
                    })
                else:
                    return Response({
                        'message': 'Payment verification failed.', 
                        'subMessage': 'Your payment verification failed'
                    }, status=400)
            else:
                return Response({
                    'message': 'Failed to verify transaction with flutterwave.', 
                    'subMessage': 'We could not verify your payment'
                }, status=400)
                
        except Transaction.DoesNotExist:
            return Response({
                'message': 'Transaction not found.',
                'subMessage': 'Could not find your transaction.'
            }, status=404)
        except Exception as e:
            print(f"Error in payment_callback: {str(e)}")
            return Response({
                'message': 'Server error occurred.',
                'subMessage': 'Please contact support.'
            }, status=500)
    else:
        return Response({
            'message': 'Payment was not successful.'
        }, status=400)


# (rest of your PayPal views unchanged – they had no editing errors)