from django.urls import path

from .views import LoginView, LogoutView, ProfileView, RegisterView, redirect_after_login

app_name = "users"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("post-login/", redirect_after_login, name="post_login"),
]
