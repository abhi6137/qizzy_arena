from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum

from .models import Attempt, AttemptAnswer, LiveSessionParticipant, Quiz, Result

User = get_user_model()


def get_leaderboard(limit: int = 20):
    return (
        User.objects.filter(role=User.Roles.STUDENT)
        .order_by("-points", "-streak_count", "username")
        .values("id", "username", "points", "streak_count", "longest_streak")[:limit]
    )


def get_student_analytics(user):
    results = Result.objects.filter(attempt__user=user).select_related("attempt", "attempt__quiz")
    avg_percentage = results.aggregate(value=Avg("percentage"))["value"] or 0
    total_quizzes = results.count()

    topic_breakdown = (
        AttemptAnswer.objects.filter(attempt__user=user)
        .exclude(is_correct__isnull=True)
        .values(topic=F("question__topic"))
        .annotate(
            total=Count("id"),
            correct=Count("id", filter=Q(is_correct=True)),
            avg_time=Avg("time_spent_seconds"),
        )
        .order_by("topic")
    )

    topic_stats = []
    weak_topics = []
    for row in topic_breakdown:
        accuracy = (row["correct"] / row["total"] * 100) if row["total"] else 0
        topic_stats.append(
            {
                "topic": row["topic"],
                "accuracy": round(accuracy, 2),
                "avg_time": round(row["avg_time"] or 0, 2),
            }
        )
        if accuracy < 60:
            weak_topics.append(row["topic"])

    trend = [
        {
            "quiz": result.attempt.quiz.title,
            "percentage": float(result.percentage),
            "date": result.generated_at.strftime("%Y-%m-%d"),
        }
        for result in results.order_by("generated_at")[:12]
    ]

    total_time = results.aggregate(value=Sum("total_time_spent_seconds"))["value"] or 0

    return {
        "total_quizzes": total_quizzes,
        "average_percentage": round(avg_percentage, 2),
        "points": user.points,
        "streak": user.streak_count,
        "trend": trend,
        "topic_stats": topic_stats,
        "weak_topics": weak_topics,
        "total_time_seconds": total_time,
    }


def get_admin_analytics(user):
    quizzes = Quiz.objects.filter(created_by=user)
    quiz_ids = list(quizzes.values_list("id", flat=True))

    attempts = Attempt.objects.filter(quiz_id__in=quiz_ids)
    results = Result.objects.filter(attempt__quiz_id__in=quiz_ids)

    quiz_health = []
    summary = (
        results.values(title=F("attempt__quiz__title"))
        .annotate(attempts=Count("id"), avg_percentage=Avg("percentage"))
        .order_by("title")
    )
    for item in summary:
        quiz_health.append(
            {
                "quiz": item["title"],
                "attempts": item["attempts"],
                "avg_percentage": round(item["avg_percentage"] or 0, 2),
            }
        )

    weak_topics = (
        AttemptAnswer.objects.filter(attempt__quiz_id__in=quiz_ids, is_correct=False)
        .values(topic=F("question__topic"))
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )

    live_participants = LiveSessionParticipant.objects.filter(session__quiz_id__in=quiz_ids).count()

    return {
        "total_quizzes": quizzes.count(),
        "total_attempts": attempts.count(),
        "avg_score": round(results.aggregate(value=Avg("percentage"))["value"] or 0, 2),
        "active_students": attempts.values("user").distinct().count(),
        "live_participants": live_participants,
        "quiz_health": quiz_health,
        "weak_topics": list(weak_topics),
    }
