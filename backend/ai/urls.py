from django.urls import path

from ai import views

urlpatterns = [
    path("api/ai/quota/", views.quota_snapshot, name="ai-quota-snapshot"),
    path("api/ai/quota/history", views.quota_history, name="ai-quota-history"),
]
