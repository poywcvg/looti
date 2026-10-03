from django.urls import path

from . import views

app_name = "panel"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("stats/", views.stats, name="stats"),
    path("search/", views.search, name="search"),
    # معامله‌ها
    path("orders/", views.orders, name="orders"),
    path("orders/<str:code>/", views.order_detail, name="order"),
    path("orders/<str:code>/action/", views.order_action, name="order_action"),
    # کاربران
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user"),
    path("users/<int:pk>/action/", views.user_action, name="user_action"),
    # آگهی‌ها
    path("ads/", views.listings_all, name="listings_all"),
    path("ads/<str:code>/action/", views.listing_action, name="listing_action"),
    # کارهای منتظر
    path("listings/", views.listings_queue, name="listings"),
    path("listings/<str:code>/", views.listing_decide, name="listing_decide"),
    path("verify/", views.verify_queue, name="verify"),
    path("verify/<str:code>/", views.verify_decide, name="verify_decide"),
    path("disputes/", views.disputes, name="disputes"),
    path("disputes/<str:code>/", views.dispute_decide, name="dispute_decide"),
    path("reports/", views.reports, name="reports"),
    path("reports/<int:pk>/", views.report_decide, name="report_decide"),
    # سایت
    path("settings/", views.site_settings, name="settings"),
    path("settings/games/<int:pk>/toggle/", views.game_toggle, name="game_toggle"),
    path("activity/", views.activity, name="activity"),
]
