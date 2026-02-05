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
    user = request.user  # CustomUser
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
            "redirect_url": "http://localhost:5173/payment-status",
            "customer": {
                "email": request.user.email or "test@example.com",   # fallback if user has no email
                "phonenumber": getattr(request.user, "phone", "0700000000"),  # Flutterwave wants "phonenumber" (no underscore)
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
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=400)
@api_view(['POST'])
def payment_callback(request):
    """
    Flutterwave redirects here after payment. 
    This is NOT an authenticated endpoint (Flutterwave can't send auth tokens).
    We need to get parameters from request.GET (query params in redirect).
    """
    # Get parameters from query string (Flutterwave redirects with these)
    status = request.GET.get("status") 
    tx_ref = request.GET.get("tx_ref") 
    transaction_id = request.GET.get("transaction_id")

    # We can't use request.user here because Flutterwave doesn't authenticate
    # Instead, we find the user via the transaction
    
    if status == 'successful':
        try:
            # Verify transaction with Flutterwave
            headers = {
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"
            }

            response = requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify", headers=headers)
            response_data = response.json()

            if response_data['status'] == 'success':
                # Get transaction by ref
                transaction = Transaction.objects.get(ref=tx_ref)
                user = transaction.user  # Get user from transaction

                # Confirm the transaction details
                if (response_data['data']['status'] == 'successful'
                    and float(response_data['data']['amount']) == float(transaction.amount)
                    and response_data['data']['currency'] == transaction.currency):
                    
                    # Update transaction and cart status to paid
                    transaction.status = 'completed'
                    transaction.save()

                    cart = transaction.cart
                    cart.paid = True
                    cart.user = user  # Use user from transaction
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
        

# Helper function to get PayPal access token (client credentials)
def get_paypal_access_token():
    url = "https://api-m.sandbox.paypal.com/v1/oauth2/token"  # change to api-m.paypal.com for live
    auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET)
    data = {"grant_type": "client_credentials"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, auth=auth, data=data, headers=headers)
    response.raise_for_status()
    return response.json()["access_token"]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def initiate_payment(request):
    """
    Creates a PayPal order.
    """
    try:
        cart_code = request.data.get("cart_code")
        if not cart_code:
            return Response({"error": "cart_code is required"}, status=400)

        cart = get_object_or_404(Cart, cart_code=cart_code)
        user = request.user
        
        amount = sum([item.quantity * item.product.price for item in cart.items.all()])
        tax = Decimal("4.00")
        total_amount = amount + tax

        # Generate unique ref
        tx_ref = str(uuid.uuid4())

        # Create pending transaction record
        transaction = Transaction.objects.create(
            ref=tx_ref,
            cart=cart,
            amount=total_amount,
            currency="KES",  # Store in your local currency
            user=user,
            status="pending"
        )

        # Get PayPal token
        access_token = get_paypal_access_token()

        # PayPal create order payload
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": tx_ref,  # Store your ref here
                    "description": "Shoppit Cart Payment",
                    "amount": {
                        "currency_code": "USD",  # PayPal requires USD
                        "value": str(total_amount.quantize(Decimal("0.00"))),
                    }
                }
            ],
            "application_context": {
                "brand_name": "Shoppit",
                "locale": "en-US",
                "user_action": "PAY_NOW",
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = "https://api-m.sandbox.paypal.com/v2/checkout/orders"
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        order_id = data["id"]

        # Store PayPal order ID in transaction
        transaction.paypal_order_id = order_id
        transaction.save()

        # Return BOTH order_id AND tx_ref to frontend
        return Response({
            "order_id": order_id,
            "tx_ref": tx_ref,  # IMPORTANT: Send this back too!
            "status": "order_created",
            "message": "PayPal order created successfully."
        }, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def capture_payment(request):
    """
    Captures the approved PayPal order.
    Now accepts EITHER order_id OR tx_ref.
    """
    try:
        order_id = request.data.get("order_id")
        tx_ref = request.data.get("tx_ref")
        
        if not order_id and not tx_ref:
            return Response({
                "error": "Either order_id or tx_ref is required"
            }, status=400)

        user = request.user

        # Find transaction by either paypal_order_id OR ref
        if order_id:
            # Try to find by PayPal order ID
            transaction = Transaction.objects.get(paypal_order_id=order_id, user=user)
        else:
            # Try to find by your internal ref
            transaction = Transaction.objects.get(ref=tx_ref, user=user)

        # If we found by tx_ref but need order_id for PayPal API
        if not order_id and transaction.paypal_order_id:
            order_id = transaction.paypal_order_id
        elif not order_id:
            return Response({
                "error": "PayPal order ID not found for this transaction"
            }, status=400)

        access_token = get_paypal_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        url = f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{order_id}/capture"
        response = requests.post(url, json={}, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data["status"] == "COMPLETED":
            # Update transaction
            transaction.status = "completed"
            transaction.save()

            # Update cart
            cart = transaction.cart
            cart.paid = True
            cart.user = user
            cart.save()

            CartItem.objects.filter(cart=cart).update(cart_paid=True)

            return Response({
                "message": "Payment captured successfully!",
                "subMessage": "Your payment has been completed."
            })

        else:
            return Response({
                "message": "Payment capture failed.",
                "subMessage": f"Status: {data.get('status')}"
            }, status=400)

    except Transaction.DoesNotExist:
        return Response({
            "error": "Transaction not found or you don't have permission"
        }, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
