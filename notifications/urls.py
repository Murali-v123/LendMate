from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notification_history, name="history"),
    path("notifications/<int:pk>/retry/", views.retry_notification, name="retry"),
    path("notifications/webhook/whatsapp/", views.whatsapp_webhook, name="whatsapp_webhook"),
]
