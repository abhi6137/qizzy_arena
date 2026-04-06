from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "role",
        "points",
        "streak_count",
        "is_active",
        "is_staff",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Quizy+ Profile",
            {
                "fields": (
                    "role",
                    "points",
                    "streak_count",
                    "longest_streak",
                    "last_quiz_date",
                )
            },
        ),
    )
