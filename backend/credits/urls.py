from django.urls import path

from . import views

urlpatterns = [
    path("credits/wallet", views.WalletView.as_view(), name="credits-wallet"),
    path("credits/quote", views.QuoteView.as_view(), name="credits-quote"),
    path("credits/transactions", views.TransactionListView.as_view(), name="credits-transactions"),
]
