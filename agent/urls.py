from django.urls import path

from agent import views

urlpatterns = [
    path("sessions/", views.ResearchSessionCreateView.as_view(), name="session-create"),
    path("sessions/<int:session_id>/", views.ResearchSessionDetailView.as_view(), name="session-detail"),
    path("repos/sessions/", views.RepoSessionsListView.as_view(), name="repo-sessions"),
]
