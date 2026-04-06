from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.utils import timezone
from django.views.generic import TemplateView

from quiz.analytics import get_admin_analytics, get_leaderboard, get_student_analytics
from quiz.models import DailyChallenge, LiveQuizSession, Quiz, Result


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        context["featured_quizzes"] = (
            Quiz.objects.filter(is_published=True)
            .filter(Q(start_at__isnull=True) | Q(start_at__lte=now), Q(end_at__isnull=True) | Q(end_at__gte=now))
            .annotate(active_question_count=Count("questions", filter=Q(questions__is_active=True)))[:6]
        )
        context["daily_challenge"] = (
            DailyChallenge.objects.filter(date=timezone.localdate(), is_active=True)
            .select_related("quiz")
            .first()
        )
        context["leaderboard"] = get_leaderboard(limit=5)
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["is_admin"] = user.is_admin
        now = timezone.now()

        if user.is_admin:
            context["admin_metrics"] = get_admin_analytics(user)
            context["recent_quizzes"] = Quiz.objects.filter(created_by=user).annotate(
                active_question_count=Count("questions", filter=Q(questions__is_active=True))
            )[:8]
            context["live_sessions"] = LiveQuizSession.objects.filter(
                host=user,
                status__in=[LiveQuizSession.Status.LOBBY, LiveQuizSession.Status.LIVE],
            )[:6]
        else:
            context["student_metrics"] = get_student_analytics(user)
            context["available_quizzes"] = (
                Quiz.objects.filter(is_published=True)
                .filter(Q(start_at__isnull=True) | Q(start_at__lte=now), Q(end_at__isnull=True) | Q(end_at__gte=now))
                .annotate(active_question_count=Count("questions", filter=Q(questions__is_active=True)))[:8]
            )
            context["latest_results"] = Result.objects.filter(attempt__user=user).select_related(
                "attempt",
                "attempt__quiz",
            )[:6]

        return context
