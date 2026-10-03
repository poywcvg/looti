from django.urls import path

from . import views

app_name = "chat"
urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("start/<str:code>/", views.start, name="start"),
    path("<int:pk>/", views.thread, name="thread"),
    path("<int:pk>/send/", views.send, name="send"),
    path("<int:pk>/poll/", views.poll, name="poll"),
]
