from django.urls import path

from . import views

urlpatterns = [
    path("payments/gateways", views.GatewaysView.as_view(), name="payments-gateways"),
    path("payments/orders", views.OrdersView.as_view(), name="payments-orders"),
    path("payments/orders/<uuid:order_id>", views.OrderView.as_view(), name="payments-order"),
    path("payments/webhooks/<str:gateway>", views.WebhookView.as_view(), name="payments-webhook"),
]
