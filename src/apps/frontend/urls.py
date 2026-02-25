from django.urls import path

from src.apps.frontend import views

app_name = "frontend"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("reset-password/<str:token>/", views.password_reset_confirm_view, name="password_reset_confirm"),
    path("activate/<uuid:invitation_token>/", views.activate_view, name="activate"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
]