from django.urls import path

from . import views

app_name = "escrow"
urlpatterns = [
    path("", views.order_list, name="list"),
    path("buy/<str:code>/", views.buy, name="buy"),
    path("<str:code>/", views.detail, name="detail"),
    path("<str:code>/pay/", views.pay, name="pay"),
    path("<str:code>/deliver/", views.deliver, name="deliver"),
    path("<str:code>/confirm/", views.confirm, name="confirm"),
    path("<str:code>/dispute/", views.dispute, name="dispute"),
    path("<str:code>/cancel/", views.cancel, name="cancel"),
    path("<str:code>/message/", views.message, name="message"),
]
