from django.urls import path

from . import views

urlpatterns = [
    path("credits/wallet", views.WalletView.as_view(), name="credits-wallet"),
    path("credits/balance", views.BalanceView.as_view(), name="credits-balance"),
    path("credits/notices", views.NoticesView.as_view(), name="credits-notices"),
    path("credits/retry-quote", views.RetryQuoteView.as_view(), name="credits-retry-quote"),
    path("credits/quote", views.QuoteView.as_view(), name="credits-quote"),
    path("credits/transactions", views.TransactionListView.as_view(), name="credits-transactions"),
    path("credits/plans", views.PlansView.as_view(), name="credits-plans"),
    path("credits/streak", views.StreakView.as_view(), name="credits-streak"),
    path("credits/streak/repair", views.StreakRepairView.as_view(), name="credits-streak-repair"),
]
