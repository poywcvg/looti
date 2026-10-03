from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Payment, User, WalletTransaction


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["phone", "username", "email", "display_name", "wallet_balance", "is_staff", "is_active", "date_joined"]
    list_filter = ["is_staff", "is_active"]
    search_fields = ["phone", "username", "email", "display_name"]
    fieldsets = [
        (None, {"fields": ["phone", "username", "email", "password"]}),
        ("پروفایل", {"fields": ["display_name", "bio", "avatar", "sheba", "wallet_balance"]}),
        ("دسترسی", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("زمان‌ها", {"fields": ["date_joined", "last_seen", "last_login"]}),
    ]
    add_fieldsets = [(None, {"classes": ["wide"], "fields": ["phone", "password1", "password2"]})]
    readonly_fields = ["wallet_balance", "last_seen", "last_login"]


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "amount", "balance_after", "created_at"]
    list_filter = ["kind"]
    search_fields = ["user__phone", "description"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["user", "amount", "status", "ref_id", "created_at"]
    list_filter = ["status"]
