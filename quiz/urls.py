from django.urls import path

from .views import (
    AdminAnalyticsView,
    AdminQuestionCreateView,
    AdminQuestionDeleteView,
    AdminQuestionGeneratorView,
    AdminQuestionListView,
    AdminQuestionUpdateView,
    AdminQuizCreateView,
    AdminQuizDeleteView,
    AdminQuizListView,
    AdminQuizUpdateView,
    AttemptHistoryView,
    AttemptPlayView,
    AttemptResultView,
    BadgeGalleryView,
    LeaderboardView,
    LiveSessionControlView,
    LiveSessionCreateView,
    LiveSessionJoinView,
    QuizCatalogView,
    StudentAnalyticsView,
    attempt_event,
    attempt_question_state,
    attempt_save_answer,
    attempt_submit,
    export_result_pdf,
    live_leaderboard_api,
    start_daily_challenge,
    start_quiz_attempt,
)

app_name = "quiz"

urlpatterns = [
    path("", QuizCatalogView.as_view(), name="catalog"),
    path("history/", AttemptHistoryView.as_view(), name="attempt_history"),
    path("analytics/student/", StudentAnalyticsView.as_view(), name="student_analytics"),
    path("analytics/admin/", AdminAnalyticsView.as_view(), name="admin_analytics"),
    path("leaderboard/", LeaderboardView.as_view(), name="leaderboard"),
    path("badges/", BadgeGalleryView.as_view(), name="badges"),
    path("daily-challenge/start/", start_daily_challenge, name="daily_challenge_start"),

    path("admin/quizzes/", AdminQuizListView.as_view(), name="admin_quiz_list"),
    path("admin/quizzes/new/", AdminQuizCreateView.as_view(), name="admin_quiz_create"),
    path("admin/quizzes/<int:pk>/edit/", AdminQuizUpdateView.as_view(), name="admin_quiz_edit"),
    path("admin/quizzes/<int:pk>/delete/", AdminQuizDeleteView.as_view(), name="admin_quiz_delete"),
    path(
        "admin/quizzes/<int:quiz_id>/questions/",
        AdminQuestionListView.as_view(),
        name="admin_question_list",
    ),
    path(
        "admin/quizzes/<int:quiz_id>/questions/new/",
        AdminQuestionCreateView.as_view(),
        name="admin_question_create",
    ),
    path("admin/questions/<int:pk>/edit/", AdminQuestionUpdateView.as_view(), name="admin_question_edit"),
    path(
        "admin/questions/<int:pk>/delete/",
        AdminQuestionDeleteView.as_view(),
        name="admin_question_delete",
    ),
    path(
        "admin/quizzes/<int:quiz_id>/generate/",
        AdminQuestionGeneratorView.as_view(),
        name="admin_question_generate",
    ),

    path("quizzes/<slug:slug>/start/", start_quiz_attempt, name="start_attempt"),
    path("attempts/<int:attempt_id>/play/", AttemptPlayView.as_view(), name="attempt_play"),
    path(
        "attempts/<int:attempt_id>/question/<int:index>/",
        attempt_question_state,
        name="attempt_question_state",
    ),
    path("attempts/<int:attempt_id>/answer/", attempt_save_answer, name="attempt_save_answer"),
    path("attempts/<int:attempt_id>/submit/", attempt_submit, name="attempt_submit"),
    path("attempts/<int:attempt_id>/event/", attempt_event, name="attempt_event"),
    path("attempts/<int:attempt_id>/result/", AttemptResultView.as_view(), name="attempt_result"),
    path("attempts/<int:attempt_id>/result.pdf", export_result_pdf, name="attempt_result_pdf"),

    path("live/create/", LiveSessionCreateView.as_view(), name="live_create"),
    path("live/join/", LiveSessionJoinView.as_view(), name="live_join"),
    path("live/<int:pk>/control/", LiveSessionControlView.as_view(), name="live_control"),
    path("live/<int:session_id>/leaderboard/", live_leaderboard_api, name="live_leaderboard_api"),
]
