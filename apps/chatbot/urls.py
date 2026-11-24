from django.urls import path

from . import views

urlpatterns = [
    path("webhooks/whatsapp/", views.WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
]
