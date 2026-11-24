from django.contrib import admin

from .models import ChatMessage, Conversation


class _ReadOnly:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(_ReadOnly, admin.ModelAdmin):
    list_display = ("__str__", "user", "language", "last_inbound_at")
    list_select_related = ("user",)
    search_fields = ("wa_id", "bsuid", "user__full_name", "user__phone")


@admin.register(ChatMessage)
class ChatMessageAdmin(_ReadOnly, admin.ModelAdmin):
    list_display = ("created_at", "conversation", "role", "tool_name", "text", "status")
    list_filter = ("status", "role", "direction")
    list_select_related = ("conversation",)
    search_fields = ("conversation__wa_id", "conversation__bsuid")
    date_hierarchy = "created_at"
