from django.urls import path

from . import views

app_name = "listings"
urlpatterns = [
    path("", views.listing_list, name="list"),
    path("new/", views.create_pick, name="create_pick"),
    path("new/<slug:slug>/", views.listing_create, name="create"),
    path("saved/", views.saved, name="saved"),
    path("compare/", views.compare, name="compare"),
    path("compare/bar/", views.compare_bar, name="compare_bar"),
    path("searches/save/", views.save_search, name="save_search"),
    path("searches/<int:pk>/delete/", views.delete_search, name="delete_search"),
    path("offers/<int:pk>/respond/", views.offer_respond, name="offer_respond"),
    path("<str:code>/", views.listing_detail, name="detail"),
    path("<str:code>/edit/", views.listing_edit, name="edit"),
    path("<str:code>/archive/", views.listing_archive, name="archive"),
    path("<str:code>/boost/", views.listing_boost, name="boost"),
    path("<str:code>/bookmark/", views.bookmark_toggle, name="bookmark"),
    path("<str:code>/compare/", views.compare_toggle, name="compare_toggle"),
    path("<str:code>/report/", views.report, name="report"),
    path("<str:code>/offer/", views.offer, name="offer"),
]
