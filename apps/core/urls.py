from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("welcome/", views.landing, name="landing"),
    path("how-it-works/", views.how, name="how"),
    path("rules/", views.rules, name="rules"),
    path("search/suggest/", views.search_suggest, name="search_suggest"),
]
