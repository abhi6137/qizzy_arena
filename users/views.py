from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.contrib.auth.views import LogoutView as DjangoLogoutView
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from .forms import CustomUserCreationForm, LoginForm, ProfileUpdateForm
from .models import User


class RegisterView(CreateView):
    model = User
    template_name = "users/register.html"
    form_class = CustomUserCreationForm
    success_url = reverse_lazy("core:dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Welcome to Quizy+! Your account is ready.")
        return response


class LoginView(DjangoLoginView):
    template_name = "users/login.html"
    authentication_form = LoginForm


class LogoutView(DjangoLogoutView):
    next_page = reverse_lazy("core:home")


class ProfileView(LoginRequiredMixin, UpdateView):
    model = User
    template_name = "users/profile.html"
    form_class = ProfileUpdateForm
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated.")
        return super().form_valid(form)


def redirect_after_login(request):
    return redirect("core:dashboard")
