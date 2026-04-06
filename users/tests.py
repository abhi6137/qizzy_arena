from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserModelTests(TestCase):
    def test_streak_updates(self):
        user = User.objects.create_user(username="sam", password="pass12345")
        user.register_quiz_activity()
        self.assertEqual(user.streak_count, 1)
        self.assertEqual(user.longest_streak, 1)


class AuthenticationFlowTests(TestCase):
    def test_duplicate_username_registration_is_rejected(self):
        User.objects.create_user(username="alex", password="pass12345", email="alex1@example.com")

        response = self.client.post(
            reverse("users:register"),
            data={
                "username": "alex",
                "email": "alex2@example.com",
                "first_name": "Alex",
                "last_name": "Two",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A user with that username already exists")

    def test_invalid_login_does_not_authenticate(self):
        User.objects.create_user(username="mia", password="pass12345")

        response = self.client.post(
            reverse("users:login"),
            data={"username": "mia", "password": "wrong-pass"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_registration_assigns_student_role(self):
        response = self.client.post(
            reverse("users:register"),
            data={
                "username": "newstudent",
                "email": "newstudent@example.com",
                "first_name": "New",
                "last_name": "Student",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="newstudent")
        self.assertEqual(user.role, User.Roles.STUDENT)

    def test_logout_works_with_post(self):
        user = User.objects.create_user(username="logoutuser", password="pass12345")
        self.client.force_login(user)

        get_response = self.client.get(reverse("users:logout"))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse("users:logout"), follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(post_response.wsgi_request.user.is_authenticated)
