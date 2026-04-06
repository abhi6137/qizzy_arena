from datetime import date

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Roles(models.TextChoices):
        ADMIN = "admin", "Admin"
        STUDENT = "student", "Student"

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.STUDENT)
    points = models.PositiveIntegerField(default=0)
    streak_count = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_quiz_date = models.DateField(null=True, blank=True)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Roles.ADMIN or self.is_staff or self.is_superuser

    def register_quiz_activity(self, activity_date: date | None = None) -> None:
        activity_date = activity_date or date.today()
        if self.last_quiz_date == activity_date:
            return
        if self.last_quiz_date and (activity_date - self.last_quiz_date).days == 1:
            self.streak_count += 1
        else:
            self.streak_count = 1
        self.longest_streak = max(self.longest_streak, self.streak_count)
        self.last_quiz_date = activity_date
        self.save(update_fields=["streak_count", "longest_streak", "last_quiz_date"])

    def award_points(self, value: int) -> None:
        self.points = max(0, self.points + int(value))
        self.save(update_fields=["points"])

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"
