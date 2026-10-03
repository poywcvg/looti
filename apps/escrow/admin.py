from django.contrib import admin

from .models import Dispute, Order, OrderEvent, OrderMessage


class EventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ["actor", "icon", "text", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """تغییر وضعیت فقط از میز کار واسط انجام شود تا کیف پول‌ها هم‌خوان بمانند."""

    list_display = ["code", "listing", "buyer", "seller", "price", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["code", "buyer__phone", "seller__phone"]
    readonly_fields = [f.name for f in Order._meta.fields]
    inlines = [EventInline]


admin.site.register([Dispute, OrderMessage])
