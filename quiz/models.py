from __future__ import annotations

import random
import string
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone


class Quiz(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, default="General")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_quizzes",
    )
    time_limit_minutes = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(1), MaxValueValidator(240)]
    )
    passing_percentage = models.PositiveIntegerField(
        default=40, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    negative_marking_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    shuffle_questions = models.BooleanField(default=True)
    allow_back_navigation = models.BooleanField(default=True)
    allow_fullscreen = models.BooleanField(default=False)
    is_adaptive = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    is_daily_challenge = models.BooleanField(default=False)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def total_questions(self) -> int:
        return self.questions.filter(is_active=True).count()

    @property
    def total_marks(self) -> Decimal:
        marks = self.questions.filter(is_active=True).aggregate(total=Sum("marks"))["total"]
        return marks or Decimal("0")

    def is_active_now(self) -> bool:
        now = timezone.now()
        if not self.is_published:
            return False
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now > self.end_at:
            return False
        return True

    def get_negative_penalty(self, question_marks: Decimal) -> Decimal:
        ratio = self.negative_marking_percentage / Decimal("100")
        return (Decimal(question_marks) * ratio).quantize(Decimal("0.01"))


class Question(models.Model):
    class QuestionType(models.TextChoices):
        MCQ = "mcq", "MCQ"
        TRUE_FALSE = "tf", "True/False"
        SHORT_ANSWER = "short", "Short Answer"

    class Difficulty(models.IntegerChoices):
        EASY = 1, "Easy"
        MEDIUM = 2, "Medium"
        HARD = 3, "Hard"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    question_type = models.CharField(max_length=20, choices=QuestionType.choices)
    prompt = models.TextField()
    answer_key = models.CharField(max_length=255, blank=True)
    explanation = models.TextField(blank=True)
    topic = models.CharField(max_length=120, default="General")
    difficulty = models.PositiveSmallIntegerField(
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
        validators=[MinValueValidator(1), MaxValueValidator(3)],
    )
    marks = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.00"))
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["quiz", "difficulty"]),
            models.Index(fields=["quiz", "topic"]),
        ]

    def __str__(self) -> str:
        return f"{self.quiz.title}: {self.prompt[:60]}"


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("question", "order")

    def __str__(self) -> str:
        return self.text


class LiveQuizSession(models.Model):
    class Status(models.TextChoices):
        LOBBY = "lobby", "Lobby"
        LIVE = "live", "Live"
        ENDED = "ended", "Ended"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="live_sessions")
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hosted_sessions",
    )
    code = models.CharField(max_length=8, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.LOBBY)
    current_question_index = models.PositiveIntegerField(default=0)
    reveal_answers = models.BooleanField(default=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self) -> str:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not LiveQuizSession.objects.filter(code=code).exists():
                return code

    def __str__(self) -> str:
        return f"{self.quiz.title} ({self.code})"


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        SUBMITTED = "submitted", "Submitted"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    max_questions = models.PositiveIntegerField(default=0)
    adaptive_cursor = models.PositiveIntegerField(default=0)
    adaptive_current_difficulty = models.PositiveSmallIntegerField(default=Question.Difficulty.MEDIUM)
    tab_switch_count = models.PositiveIntegerField(default=0)
    full_screen_exits = models.PositiveIntegerField(default=0)
    randomized_question_ids = models.JSONField(default=list, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    is_live_attempt = models.BooleanField(default=False)
    live_session = models.ForeignKey(
        LiveQuizSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attempts",
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "quiz", "status"]),
            models.Index(fields=["started_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "quiz"],
                condition=Q(status="in_progress", live_session__isnull=True),
                name="uniq_active_attempt_per_user_quiz",
            ),
            models.UniqueConstraint(
                fields=["user", "quiz", "live_session"],
                condition=Q(status="in_progress", live_session__isnull=False),
                name="uniq_active_attempt_per_user_quiz_live",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.quiz.title} ({self.status})"

    def set_deadline(self) -> None:
        if not self.deadline_at:
            self.deadline_at = self.started_at + timezone.timedelta(minutes=self.quiz.time_limit_minutes)

    @property
    def is_expired(self) -> bool:
        if self.status != self.Status.IN_PROGRESS:
            return False
        if not self.deadline_at:
            return False
        return timezone.now() >= self.deadline_at

    def time_remaining_seconds(self) -> int:
        if not self.deadline_at:
            return self.quiz.time_limit_minutes * 60
        delta = int((self.deadline_at - timezone.now()).total_seconds())
        return max(0, delta)

    def expire_if_needed(self) -> bool:
        if self.is_expired:
            self.status = self.Status.EXPIRED
            self.submitted_at = timezone.now()
            self.save(update_fields=["status", "submitted_at"])
            return True
        return False


class AttemptQuestion(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="attempt_questions")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    served_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        unique_together = (("attempt", "question"), ("attempt", "order"))


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="attempt_answers")
    selected_option = models.ForeignKey(
        Option,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="selected_in_answers",
    )
    text_answer = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    score_awarded = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    time_spent_seconds = models.PositiveIntegerField(default=0)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("attempt", "question")

    def evaluate(self) -> None:
        question = self.question
        quiz = self.attempt.quiz

        if question.question_type in {Question.QuestionType.MCQ, Question.QuestionType.TRUE_FALSE}:
            if not self.selected_option_id:
                self.is_correct = None
            else:
                correct_option = question.options.filter(is_correct=True).first()
                self.is_correct = bool(correct_option and self.selected_option_id == correct_option.id)
        elif question.answer_key:
            submitted = (self.text_answer or "").strip().lower()
            expected = question.answer_key.strip().lower()
            self.is_correct = submitted == expected
        else:
            self.is_correct = None

        if self.is_correct is True:
            self.score_awarded = question.marks
        elif self.is_correct is False:
            self.score_awarded = -quiz.get_negative_penalty(question.marks)
        else:
            self.score_awarded = Decimal("0.00")


class Result(models.Model):
    attempt = models.OneToOneField(Attempt, on_delete=models.CASCADE, related_name="result")
    total_score = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    percentage = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    correct_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)
    unattempted_count = models.PositiveIntegerField(default=0)
    negative_score = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    total_time_spent_seconds = models.PositiveIntegerField(default=0)
    weak_topics = models.JSONField(default=list, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]


class Badge(models.Model):
    class BadgeType(models.TextChoices):
        ACCURACY = "accuracy", "Accuracy"
        STREAK = "streak", "Streak"
        PARTICIPATION = "participation", "Participation"
        CHALLENGE = "challenge", "Challenge"

    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    badge_type = models.CharField(max_length=30, choices=BadgeType.choices, default=BadgeType.PARTICIPATION)
    points_required = models.PositiveIntegerField(default=0)
    criteria = models.JSONField(default=dict, blank=True)
    icon_class = models.CharField(max_length=80, default="badge-star")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class UserBadge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges")
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="awarded_users")
    awarded_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("user", "badge")
        ordering = ["-awarded_at"]


class DailyChallenge(models.Model):
    date = models.DateField(unique=True)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="daily_challenges")
    bonus_points = models.PositiveIntegerField(default=25)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date"]


class LiveSessionParticipant(models.Model):
    session = models.ForeignKey(
        LiveQuizSession,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="live_participations")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    score = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    answers_count = models.PositiveIntegerField(default=0)
    is_connected = models.BooleanField(default=True)

    class Meta:
        unique_together = ("session", "user")
        ordering = ["-score", "joined_at"]
