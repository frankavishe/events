from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User


class AdminUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("phone", "full_name", "email", "role")


class AdminUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm

    list_display = ("phone", "full_name", "email", "role", "created_via", "is_active", "created_at")
    list_filter = ("role", "created_via", "preferred_language", "is_active", "is_staff")
    search_fields = ("phone", "full_name", "email")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "phone", "password")}),
        ("Profile", {"fields": ("full_name", "email", "preferred_language", "created_via")}),
        ("Role & access", {"fields": ("role", "is_active", "is_staff", "is_superuser")}),
        ("Permissions", {"classes": ("collapse",), "fields": ("groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "full_name", "email", "role", "password1", "password2"),
            },
        ),
    )
