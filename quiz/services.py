from __future__ import annotations

import random
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

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


@transaction.atomic
def create_attempt(user, quiz: Quiz, live_session: LiveQuizSession | None = None) -> Attempt:
    if not user.is_admin and not live_session and not quiz.is_active_now():
        raise ValidationError("This quiz is not currently available.")

    existing = Attempt.objects.filter(
        user=user,
        quiz=quiz,
        status=Attempt.Status.IN_PROGRESS,
        live_session=live_session,
    ).first()
    if existing:
        existing.expire_if_needed()
        if existing.status == Attempt.Status.IN_PROGRESS:
            return existing

    question_ids = list(quiz.questions.filter(is_active=True).values_list("id", flat=True))
    if not question_ids:
        raise ValidationError("Quiz has no active questions.")

    if quiz.shuffle_questions:
        random.shuffle(question_ids)

    try:
        attempt = Attempt.objects.create(
            user=user,
            quiz=quiz,
            max_questions=len(question_ids),
            randomized_question_ids=question_ids,
            is_live_attempt=bool(live_session),
            live_session=live_session,
        )
    except IntegrityError:
        active_attempt = Attempt.objects.filter(
            user=user,
            quiz=quiz,
            status=Attempt.Status.IN_PROGRESS,
            live_session=live_session,
        ).first()
        if active_attempt:
            return active_attempt
        raise
    attempt.set_deadline()
    attempt.save(update_fields=["deadline_at"])

    if live_session:
        LiveSessionParticipant.objects.get_or_create(session=live_session, user=user)

    return attempt


def _candidate_questions_for_adaptive(attempt: Attempt):
    answered_question_ids = set(
        AttemptAnswer.objects.filter(attempt=attempt).values_list("question_id", flat=True)
    )
    return attempt.quiz.questions.filter(is_active=True).exclude(id__in=answered_question_ids)


def _choose_adaptive_question(attempt: Attempt) -> Question | None:
    candidates = list(_candidate_questions_for_adaptive(attempt))
    if not candidates:
        return None

    target = attempt.adaptive_current_difficulty
    latest_answer = (
        AttemptAnswer.objects.filter(attempt=attempt)
        .exclude(is_correct__isnull=True)
        .select_related("question")
        .order_by("-answered_at")
        .first()
    )
    if latest_answer is not None:
        if latest_answer.is_correct:
            target = min(Question.Difficulty.HARD, target + 1)
        else:
            target = max(Question.Difficulty.EASY, target - 1)

    same_level = [q for q in candidates if q.difficulty == target]
    if same_level:
        question = random.choice(same_level)
    else:
        candidates.sort(key=lambda q: abs(q.difficulty - target))
        question = candidates[0]

    attempt.adaptive_current_difficulty = target
    attempt.save(update_fields=["adaptive_current_difficulty"])
    return question


def get_question_for_attempt(attempt: Attempt, index: int) -> Question | None:
    if attempt.expire_if_needed():
        return None

    existing = (
        AttemptQuestion.objects.filter(attempt=attempt, order=index)
        .select_related("question")
        .first()
    )
    if existing:
        return existing.question

    if index < 0 or index >= attempt.max_questions:
        return None

    if attempt.quiz.is_adaptive:
        question = _choose_adaptive_question(attempt)
    else:
        question_id = attempt.randomized_question_ids[index]
        question = attempt.quiz.questions.filter(id=question_id, is_active=True).first()

    if not question:
        return None

    AttemptQuestion.objects.create(attempt=attempt, question=question, order=index)
    return question


@transaction.atomic
def save_answer(
    attempt: Attempt,
    question: Question,
    selected_option_id: int | None,
    text_answer: str,
    time_spent_seconds: int,
) -> AttemptAnswer:
    if attempt.expire_if_needed():
        raise ValidationError("Attempt has expired.")
    if attempt.status != Attempt.Status.IN_PROGRESS:
        raise ValidationError("Attempt is not active.")

    answer, _ = AttemptAnswer.objects.get_or_create(attempt=attempt, question=question)
    answer.text_answer = (text_answer or "").strip()
    max_allowed_seconds = max(60, attempt.quiz.time_limit_minutes * 60)
    answer.time_spent_seconds = min(max_allowed_seconds, max(0, int(time_spent_seconds or 0)))

    if selected_option_id:
        answer.selected_option = Option.objects.filter(question=question, id=selected_option_id).first()
    else:
        answer.selected_option = None

    answer.evaluate()
    answer.save()

    if attempt.quiz.is_adaptive and answer.is_correct is not None:
        if answer.is_correct:
            attempt.adaptive_current_difficulty = min(
                Question.Difficulty.HARD, attempt.adaptive_current_difficulty + 1
            )
        else:
            attempt.adaptive_current_difficulty = max(
                Question.Difficulty.EASY, attempt.adaptive_current_difficulty - 1
            )
        attempt.save(update_fields=["adaptive_current_difficulty"])

    if attempt.is_live_attempt and attempt.live_session_id:
        participant = LiveSessionParticipant.objects.filter(
            session=attempt.live_session,
            user=attempt.user,
        ).first()
        if participant:
            participant.answers_count = AttemptAnswer.objects.filter(attempt=attempt).count()
            if answer.is_correct:
                participant.score += settings.QUIZY.get("LIVE_BASE_POINTS", 100)
            participant.save(update_fields=["answers_count", "score", "last_activity"])

    return answer


@transaction.atomic
def register_anti_cheat_event(attempt: Attempt, event_type: str) -> None:
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return

    if event_type == "tab_switch":
        attempt.tab_switch_count += 1
        attempt.save(update_fields=["tab_switch_count"])
    elif event_type == "fullscreen_exit":
        attempt.full_screen_exits += 1
        attempt.save(update_fields=["full_screen_exits"])


def _collect_topic_accuracy(attempt: Attempt):
    rows = (
        AttemptAnswer.objects.filter(attempt=attempt)
        .exclude(is_correct__isnull=True)
        .values("question__topic")
        .annotate(total=Count("id"), correct=Count("id", filter=Q(is_correct=True)))
    )
    weak_topics = []
    for row in rows:
        accuracy = (row["correct"] / row["total"] * 100) if row["total"] else 0
        if accuracy < 60:
            weak_topics.append(row["question__topic"])
    return weak_topics


def _award_badges(user, latest_result: Result):
    awarded = []
    badges = Badge.objects.filter(is_active=True).exclude(awarded_users__user=user)
    attempts_count = Attempt.objects.filter(user=user, status=Attempt.Status.SUBMITTED).count()

    for badge in badges:
        criteria = badge.criteria or {}
        min_points = int(criteria.get("min_points", badge.points_required or 0))
        min_percentage = Decimal(str(criteria.get("min_percentage", "0")))
        min_streak = int(criteria.get("min_streak", 0))
        min_attempts = int(criteria.get("min_attempts", 0))

        is_eligible = (
            user.points >= min_points
            and Decimal(latest_result.percentage) >= min_percentage
            and user.streak_count >= min_streak
            and attempts_count >= min_attempts
        )

        if is_eligible:
            UserBadge.objects.create(user=user, badge=badge, reason="Auto-awarded by system rules")
            awarded.append(badge)

    return awarded


@transaction.atomic
def finalize_attempt(attempt: Attempt, force_status: str | None = None) -> Result:
    if attempt.status in {Attempt.Status.SUBMITTED, Attempt.Status.EXPIRED} and hasattr(attempt, "result"):
        return attempt.result

    if attempt.status == Attempt.Status.IN_PROGRESS:
        if force_status:
            attempt.status = force_status
        else:
            attempt.status = Attempt.Status.EXPIRED if attempt.is_expired else Attempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

    questions = attempt.quiz.questions.filter(id__in=attempt.randomized_question_ids, is_active=True)
    answers = {a.question_id: a for a in AttemptAnswer.objects.filter(attempt=attempt).select_related("question")}

    total_score = Decimal("0.00")
    max_score = Decimal("0.00")
    correct_count = 0
    wrong_count = 0
    unattempted_count = 0
    negative_score = Decimal("0.00")
    total_time = 0

    for question in questions:
        max_score += question.marks
        answer = answers.get(question.id)
        if not answer:
            unattempted_count += 1
            continue

        answer.evaluate()
        answer.save(update_fields=["is_correct", "score_awarded", "answered_at"])

        total_score += answer.score_awarded
        total_time += answer.time_spent_seconds

        if answer.is_correct is True:
            correct_count += 1
        elif answer.is_correct is False:
            wrong_count += 1
            if answer.score_awarded < 0:
                negative_score += abs(answer.score_awarded)
        else:
            has_user_input = bool(answer.selected_option_id or (answer.text_answer or "").strip())
            if not has_user_input:
                unattempted_count += 1

    percentage = Decimal("0.00")
    if max_score > 0:
        percentage = (total_score / max_score) * Decimal("100")

    weak_topics = _collect_topic_accuracy(attempt)

    result, created = Result.objects.update_or_create(
        attempt=attempt,
        defaults={
            "total_score": total_score.quantize(Decimal("0.01")),
            "max_score": max_score.quantize(Decimal("0.01")),
            "percentage": percentage.quantize(Decimal("0.01")),
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "unattempted_count": unattempted_count,
            "negative_score": negative_score.quantize(Decimal("0.01")),
            "total_time_spent_seconds": total_time,
            "weak_topics": weak_topics,
        },
    )

    if created:
        points = correct_count * settings.QUIZY.get("CORRECT_ANSWER_POINTS", 10)

        challenge = DailyChallenge.objects.filter(
            date=timezone.localdate(),
            quiz=attempt.quiz,
            is_active=True,
        ).first()
        if challenge:
            points += challenge.bonus_points

        attempt.user.award_points(points)
        attempt.user.register_quiz_activity(timezone.localdate())
        _award_badges(attempt.user, result)

        if attempt.user.email:
            try:
                send_mail(
                    subject=f"Quiz Result: {attempt.quiz.title}",
                    message=(
                        f"You scored {result.total_score}/{result.max_score} "
                        f"({result.percentage}%)."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[attempt.user.email],
                    fail_silently=True,
                )
            except Exception:
                pass

    return result


def build_navigation_payload(attempt: Attempt):
    answers = set(AttemptAnswer.objects.filter(attempt=attempt).values_list("question_id", flat=True))
    served = AttemptQuestion.objects.filter(attempt=attempt).order_by("order")

    payload = []
    for item in served:
        payload.append(
            {
                "order": item.order,
                "question_id": item.question_id,
                "answered": item.question_id in answers,
            }
        )

    return payload


def generate_questions_from_text(
    quiz: Quiz,
    source_text: str,
    number_of_questions: int,
    topic: str,
    difficulty: int,
):
    clean_sentences = [
        sentence.strip()
        for sentence in re.split(r"[.!?]", source_text)
        if len(sentence.strip().split()) >= 6
    ]
    if not clean_sentences:
        return 0

    vocabulary = []
    for sentence in clean_sentences:
        vocabulary.extend(re.findall(r"\b[A-Za-z]{4,}\b", sentence))

    if len(vocabulary) < 4:
        return 0

    generated_count = 0
    next_order = quiz.questions.count()
    random.shuffle(clean_sentences)

    for sentence in clean_sentences[:number_of_questions]:
        words = re.findall(r"\b[A-Za-z]{4,}\b", sentence)
        if len(words) < 2:
            continue

        answer = random.choice(words)
        prompt = sentence.replace(answer, "____", 1)
        prompt = f"Fill in the blank: {prompt.strip()}"

        question = Question.objects.create(
            quiz=quiz,
            question_type=Question.QuestionType.MCQ,
            prompt=prompt,
            answer_key=answer,
            explanation=f"The correct word is '{answer}'.",
            topic=topic,
            difficulty=int(difficulty),
            marks=Decimal("1.00"),
            order=next_order,
        )

        distractor_pool = [w for w in set(vocabulary) if w.lower() != answer.lower()]
        distractors = random.sample(distractor_pool, k=min(3, len(distractor_pool)))
        options = distractors + [answer]
        while len(options) < 4:
            options.append(f"Option {len(options) + 1}")
        random.shuffle(options)

        for idx, value in enumerate(options):
            Option.objects.create(
                question=question,
                text=value,
                is_correct=value.lower() == answer.lower(),
                order=idx,
            )

        generated_count += 1
        next_order += 1

    return generated_count


def get_live_leaderboard(session: LiveQuizSession):
    return list(
        session.participants.select_related("user")
        .order_by("-score", "joined_at")
        .values("user__username", "score", "answers_count")
    )


def join_live_session(user, code: str):
    session = LiveQuizSession.objects.filter(
        code=code.upper(),
        status__in=[LiveQuizSession.Status.LOBBY, LiveQuizSession.Status.LIVE],
    ).first()
    if not session:
        raise ValidationError("Invalid or inactive session code.")

    participant, _ = LiveSessionParticipant.objects.get_or_create(session=session, user=user)
    participant.is_connected = True
    participant.save(update_fields=["is_connected", "last_activity"])

    attempt = create_attempt(user, session.quiz, live_session=session)
    return session, attempt
