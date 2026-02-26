from django.urls import path

from src.apps.orgadmin import views

app_name = "orgadmin"

urlpatterns = [
    path("", views.dashboard_view, name="oa_dashboard"),
    path("members/", views.members_view, name="oa_members"),
    path("settings/", views.settings_view, name="oa_settings"),
]
