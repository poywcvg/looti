from django.urls import path

from . import views

app_name = "reviews"
urlpatterns = [
    path("<str:order_code>/", views.create, name="create"),
]
