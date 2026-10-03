from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=static_url("img/brand/favicon.svg"), permanent=True)),
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("account/", include("apps.accounts.urls")),
    path("ads/", include("apps.listings.urls")),
    path("orders/", include("apps.escrow.urls")),
    path("chat/", include("apps.chat.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("reviews/", include("apps.reviews.urls")),
    path("panel/", include("apps.panel.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "apps.core.views.not_found"
