from django.urls import path

from guided_tours import views

app_name = "guided_tours"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("api/progress/", views.progress_view, name="progress"),
    path("api/events/", views.events_view, name="events"),
]
