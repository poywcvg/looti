from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/verify/", views.verify_view, name="verify"),
    path("login/password/", views.login_password, name="login_password"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/identity/", views.settings_identity, name="settings_identity"),
    path("settings/password/", views.settings_password, name="settings_password"),
    path("settings/password/remove/", views.settings_password_remove, name="settings_password_remove"),
    path("wallet/", views.wallet, name="wallet"),
    path("wallet/deposit/", views.deposit, name="deposit"),
    path("wallet/withdraw/", views.withdraw, name="withdraw"),
    path("pay/<str:token>/", views.gateway, name="gateway"),
    path("u/<int:pk>/", views.profile, name="profile"),
]
