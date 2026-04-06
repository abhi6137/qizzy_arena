import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attempt, Option, Question, Quiz
from .services import create_attempt, finalize_attempt, get_question_for_attempt, save_answer

User = get_user_model()


class QuizEngineTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin1",
            password="pass12345",
            role=User.Roles.ADMIN,
        )
        self.student = User.objects.create_user(
            username="student1",
            password="pass12345",
            role=User.Roles.STUDENT,
        )

        self.quiz = Quiz.objects.create(
            title="Python Basics",
            slug="python-basics",
            created_by=self.admin_user,
            time_limit_minutes=10,
            negative_marking_percentage=Decimal("25.00"),
            is_published=True,
            is_adaptive=False,
        )

        self.q1 = Question.objects.create(
            quiz=self.quiz,
            question_type=Question.QuestionType.MCQ,
            prompt="What is 2 + 2?",
            topic="Math",
            difficulty=Question.Difficulty.EASY,
            marks=Decimal("2.00"),
            order=1,
        )
        self.q1_correct = Option.objects.create(question=self.q1, text="4", is_correct=True, order=1)
        Option.objects.create(question=self.q1, text="5", is_correct=False, order=2)

        self.q2 = Question.objects.create(
            quiz=self.quiz,
            question_type=Question.QuestionType.TRUE_FALSE,
            prompt="Python is statically typed.",
            topic="Theory",
            difficulty=Question.Difficulty.MEDIUM,
            marks=Decimal("1.00"),
            order=2,
        )
        self.q2_correct = Option.objects.create(question=self.q2, text="False", is_correct=True, order=1)
        self.q2_wrong = Option.objects.create(question=self.q2, text="True", is_correct=False, order=2)

    def test_finalize_attempt_with_negative_marking(self):
        attempt = create_attempt(self.student, self.quiz)
        save_answer(attempt, self.q1, self.q1_correct.id, "", 12)
        save_answer(attempt, self.q2, self.q2_wrong.id, "", 8)

        result = finalize_attempt(attempt)

        self.assertEqual(result.total_score, Decimal("1.75"))
        self.assertEqual(result.max_score, Decimal("3.00"))
        self.assertEqual(result.correct_count, 1)
        self.assertEqual(result.wrong_count, 1)
        self.assertEqual(result.unattempted_count, 0)

    def test_partial_submission_tracks_unattempted(self):
        attempt = create_attempt(self.student, self.quiz)
        save_answer(attempt, self.q1, self.q1_correct.id, "", 5)

        result = finalize_attempt(attempt)

        self.assertEqual(result.correct_count, 1)
        self.assertEqual(result.unattempted_count, 1)

    def test_timer_expiry_returns_expired_payload(self):
        attempt = create_attempt(self.student, self.quiz)
        attempt.deadline_at = timezone.now() - timezone.timedelta(seconds=1)
        attempt.save(update_fields=["deadline_at"])

        self.client.force_login(self.student)
        response = self.client.get(reverse("quiz:attempt_question_state", args=[attempt.id, 0]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("expired"))
        self.assertIn("redirect_url", payload)

    def test_invalid_answer_payload_returns_400(self):
        attempt = create_attempt(self.student, self.quiz)
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("quiz:attempt_save_answer", args=[attempt.id]),
            data="{invalid json}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unanswered_objective_is_not_marked_wrong(self):
        attempt = create_attempt(self.student, self.quiz)
        save_answer(attempt, self.q1, None, "", 3)

        result = finalize_attempt(attempt)

        self.assertEqual(result.total_score, Decimal("0.00"))
        self.assertEqual(result.wrong_count, 0)
        self.assertEqual(result.unattempted_count, 2)

    def test_out_of_range_question_index_does_not_submit_attempt(self):
        attempt = create_attempt(self.student, self.quiz)
        self.client.force_login(self.student)

        response = self.client.get(reverse("quiz:attempt_question_state", args=[attempt.id, 999]))
        attempt.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(attempt.status, Attempt.Status.IN_PROGRESS)

    def test_cannot_save_answer_for_unserved_question(self):
        attempt = create_attempt(self.student, self.quiz)
        self.client.force_login(self.student)

        payload = {
            "question_id": self.q1.id,
            "selected_option_id": self.q1_correct.id,
            "text_answer": "",
            "time_spent_seconds": 5,
        }
        response = self.client.post(
            reverse("quiz:attempt_save_answer", args=[attempt.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_submit_after_expiry_marks_attempt_expired(self):
        attempt = create_attempt(self.student, self.quiz)
        attempt.deadline_at = timezone.now() - timezone.timedelta(seconds=5)
        attempt.save(update_fields=["deadline_at"])

        self.client.force_login(self.student)
        response = self.client.post(reverse("quiz:attempt_submit", args=[attempt.id]))

        self.assertEqual(response.status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, Attempt.Status.EXPIRED)

    def test_invalid_anti_cheat_event_rejected(self):
        attempt = create_attempt(self.student, self.quiz)
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("quiz:attempt_event", args=[attempt.id]),
            data=json.dumps({"event_type": "unknown_event"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_finalize_attempt_is_idempotent_for_points(self):
        attempt = create_attempt(self.student, self.quiz)
        save_answer(attempt, self.q1, self.q1_correct.id, "", 10)

        initial_points = self.student.points
        first_result = finalize_attempt(attempt)
        self.student.refresh_from_db()
        points_after_first = self.student.points

        second_result = finalize_attempt(attempt)
        self.student.refresh_from_db()

        self.assertEqual(first_result.id, second_result.id)
        self.assertGreater(points_after_first, initial_points)
        self.assertEqual(self.student.points, points_after_first)

    def test_manual_review_short_answer_not_marked_unattempted(self):
        short_q = Question.objects.create(
            quiz=self.quiz,
            question_type=Question.QuestionType.SHORT_ANSWER,
            prompt="Explain duck typing.",
            answer_key="",
            topic="Theory",
            difficulty=Question.Difficulty.MEDIUM,
            marks=Decimal("1.00"),
            order=3,
        )

        attempt = create_attempt(self.student, self.quiz)
        save_answer(attempt, short_q, None, "Python checks behavior, not explicit type.", 18)

        result = finalize_attempt(attempt)

        self.assertEqual(result.wrong_count, 0)
        self.assertEqual(result.unattempted_count, 2)


class QuizAccessTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin2",
            password="pass12345",
            role=User.Roles.ADMIN,
        )
        self.student = User.objects.create_user(
            username="student2",
            password="pass12345",
            role=User.Roles.STUDENT,
        )
        self.quiz = Quiz.objects.create(
            title="Unavailable Quiz",
            slug="unavailable-quiz",
            created_by=self.admin_user,
            is_published=False,
        )

    def test_cannot_start_unpublished_quiz(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("quiz:start_attempt", args=[self.quiz.slug]))
        self.assertEqual(response.status_code, 302)


class AttemptConstraintTests(TestCase):
    def test_db_blocks_duplicate_active_non_live_attempts(self):
        admin_user = User.objects.create_user(
            username="admin3",
            password="pass12345",
            role=User.Roles.ADMIN,
        )
        student = User.objects.create_user(
            username="student3",
            password="pass12345",
            role=User.Roles.STUDENT,
        )
        quiz = Quiz.objects.create(
            title="Constraint Quiz",
            slug="constraint-quiz",
            created_by=admin_user,
            is_published=True,
        )
        Question.objects.create(
            quiz=quiz,
            question_type=Question.QuestionType.MCQ,
            prompt="Constraint check?",
            topic="General",
            difficulty=Question.Difficulty.EASY,
            marks=Decimal("1.00"),
            order=1,
        )

        first = create_attempt(student, quiz)
        with self.assertRaises(IntegrityError):
            Attempt.objects.create(
                user=student,
                quiz=quiz,
                status=Attempt.Status.IN_PROGRESS,
                deadline_at=timezone.now() + timezone.timedelta(minutes=10),
                max_questions=first.max_questions,
                randomized_question_ids=first.randomized_question_ids,
            )


class AdaptiveEngineTests(TestCase):
    def test_adaptive_difficulty_moves_up_and_down(self):
        admin_user = User.objects.create_user(
            username="admin4",
            password="pass12345",
            role=User.Roles.ADMIN,
        )
        student = User.objects.create_user(
            username="student4",
            password="pass12345",
            role=User.Roles.STUDENT,
        )
        quiz = Quiz.objects.create(
            title="Adaptive Quiz",
            slug="adaptive-quiz",
            created_by=admin_user,
            is_published=True,
            is_adaptive=True,
            shuffle_questions=False,
        )

        q_easy = Question.objects.create(
            quiz=quiz,
            question_type=Question.QuestionType.MCQ,
            prompt="Easy question",
            topic="Level",
            difficulty=Question.Difficulty.EASY,
            marks=Decimal("1.00"),
            order=1,
        )
        q_medium = Question.objects.create(
            quiz=quiz,
            question_type=Question.QuestionType.MCQ,
            prompt="Medium question",
            topic="Level",
            difficulty=Question.Difficulty.MEDIUM,
            marks=Decimal("1.00"),
            order=2,
        )
        q_hard = Question.objects.create(
            quiz=quiz,
            question_type=Question.QuestionType.MCQ,
            prompt="Hard question",
            topic="Level",
            difficulty=Question.Difficulty.HARD,
            marks=Decimal("1.00"),
            order=3,
        )

        Option.objects.create(question=q_easy, text="E1", is_correct=True, order=1)
        Option.objects.create(question=q_easy, text="E2", is_correct=False, order=2)

        medium_correct = Option.objects.create(question=q_medium, text="M1", is_correct=True, order=1)
        Option.objects.create(question=q_medium, text="M2", is_correct=False, order=2)

        hard_correct = Option.objects.create(question=q_hard, text="H1", is_correct=True, order=1)
        hard_wrong = Option.objects.create(question=q_hard, text="H2", is_correct=False, order=2)

        attempt = create_attempt(student, quiz)

        first_question = get_question_for_attempt(attempt, 0)
        self.assertEqual(first_question.difficulty, Question.Difficulty.MEDIUM)

        save_answer(attempt, first_question, medium_correct.id, "", 4)
        second_question = get_question_for_attempt(attempt, 1)
        self.assertEqual(second_question.difficulty, Question.Difficulty.HARD)

        save_answer(attempt, second_question, hard_wrong.id, "", 4)
        third_question = get_question_for_attempt(attempt, 2)
        self.assertEqual(third_question.difficulty, Question.Difficulty.EASY)
