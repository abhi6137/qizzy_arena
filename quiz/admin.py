from django.contrib import admin

from .models import (
    Attempt,
    AttemptAnswer,
    AttemptQuestion,
    Badge,
    DailyChallenge,
    LiveQuizSession,
    LiveSessionParticipant,
    Option,
    Question,
    Quiz,
    Result,
    UserBadge,
)


class OptionInline(admin.TabularInline):
    model = Option
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "question_type", "difficulty", "topic", "marks", "is_active")
    list_filter = ("question_type", "difficulty", "topic", "is_active")
    search_fields = ("prompt", "topic")
    inlines = [OptionInline]


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "created_by",
        "time_limit_minutes",
        "is_adaptive",
        "is_published",
        "is_daily_challenge",
    )
    list_filter = ("is_published", "is_adaptive", "is_daily_challenge", "category")
    search_fields = ("title", "category")
    prepopulated_fields = {"slug": ("title",)}


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ("question", "selected_option", "text_answer", "is_correct", "score_awarded")


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "quiz", "status", "started_at", "submitted_at", "tab_switch_count")
    list_filter = ("status", "quiz")
    readonly_fields = ("started_at", "submitted_at")
    inlines = [AttemptAnswerInline]


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("attempt", "total_score", "percentage", "correct_count", "wrong_count")
    list_filter = ("attempt__quiz",)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("name", "badge_type", "points_required", "is_active")
    list_filter = ("badge_type", "is_active")


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "badge", "awarded_at")
    list_filter = ("badge",)


@admin.register(DailyChallenge)
class DailyChallengeAdmin(admin.ModelAdmin):
    list_display = ("date", "quiz", "bonus_points", "is_active")
    list_filter = ("is_active",)


@admin.register(LiveQuizSession)
class LiveQuizSessionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "host", "code", "status", "created_at")
    list_filter = ("status",)


@admin.register(LiveSessionParticipant)
class LiveSessionParticipantAdmin(admin.ModelAdmin):
    list_display = ("session", "user", "score", "answers_count", "is_connected")
    list_filter = ("is_connected",)


@admin.register(AttemptQuestion)
class AttemptQuestionAdmin(admin.ModelAdmin):
    list_display = ("attempt", "question", "order", "served_at")
