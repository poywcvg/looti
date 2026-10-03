from django.contrib import admin

from .models import Bookmark, Game, Listing, ListingImage, Offer, Report, SavedSearch


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["name", "name_en", "slug", "order", "is_active"]
    list_editable = ["order", "is_active"]
    prepopulated_fields = {"slug": ["name_en"]}


class ImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["code", "title", "game", "seller", "price", "platform_display_multi", "open_to_trade", "status", "created_at"]
    list_filter = ["status", "game", "platform", "open_to_trade"]
    search_fields = ["code", "title", "seller__phone"]
    inlines = [ImageInline]

    @admin.display(description="پلتفرم‌ها")
    def platform_display_multi(self, obj):
        return obj.platform_display_multi


admin.site.register([Bookmark, SavedSearch, Offer])


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["listing", "reason", "reporter", "resolved", "created_at"]
    list_filter = ["resolved", "reason"]
