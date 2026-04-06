from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from .analytics import get_admin_analytics, get_leaderboard, get_student_analytics
from .forms import (
    JoinLiveSessionForm,
    LiveSessionCreateForm,
    OptionForm,
    QuestionForm,
    QuestionGeneratorForm,
    QuizForm,
)
from .models import (
    Attempt,
    AttemptAnswer,
    Badge,
    DailyChallenge,
    LiveQuizSession,
    Option,
    Question,
    Quiz,
    Result,
    UserBadge,
)
from .services import (
    build_navigation_payload,
    create_attempt,
    finalize_attempt,
    generate_questions_from_text,
    get_live_leaderboard,
    get_question_for_attempt,
    join_live_session,
    register_anti_cheat_event,
    save_answer,
)


class BaseOptionInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        seen_orders = set()
        for form in self.forms:
            cleaned = getattr(form, "cleaned_data", None)
            if not cleaned or cleaned.get("DELETE"):
                continue

            order = cleaned.get("order")
            if order is None:
                form.add_error("order", "Order is required.")
                continue

            if order in seen_orders:
                form.add_error("order", "Each option order must be unique.")
            seen_orders.add(order)

OptionFormSet = inlineformset_factory(
    Question,
    Option,
    form=OptionForm,
    formset=BaseOptionInlineFormSet,
    extra=4,
    can_delete=True,
)


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_admin

    def handle_no_permission(self):
        raise PermissionDenied


class StudentRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return not self.request.user.is_admin

    def handle_no_permission(self):
        raise PermissionDenied


def _get_owned_attempt(request, attempt_id: int) -> Attempt:
    attempt = get_object_or_404(Attempt.objects.select_related("quiz", "user"), pk=attempt_id)
    if attempt.user_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return attempt


def _serialize_question(question: Question, answer: AttemptAnswer | None = None):
    payload = {
        "id": question.id,
        "prompt": question.prompt,
        "question_type": question.question_type,
        "difficulty": question.get_difficulty_display(),
        "difficulty_value": question.difficulty,
        "topic": question.topic,
        "marks": float(question.marks),
        "options": [
            {
                "id": option.id,
                "text": option.text,
            }
            for option in question.options.all()
        ],
    }
    if answer:
        payload.update(
            {
                "selected_option_id": answer.selected_option_id,
                "text_answer": answer.text_answer,
                "time_spent_seconds": answer.time_spent_seconds,
            }
        )
    return payload


def _validate_objective_options(question_type: str, formset):
    active_rows = []
    for form in formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        if form.cleaned_data.get("text"):
            active_rows.append(form.cleaned_data)

    if question_type in {Question.QuestionType.MCQ, Question.QuestionType.TRUE_FALSE}:
        if len(active_rows) < 2:
            formset.add_error(None, "At least two options are required for objective questions.")
            return False
        if sum(1 for row in active_rows if row.get("is_correct")) != 1:
            formset.add_error(None, "Exactly one option must be marked correct.")
            return False

    if question_type == Question.QuestionType.TRUE_FALSE:
        labels = {str(row.get("text", "")).strip().lower() for row in active_rows}
        if len(active_rows) != 2 or labels != {"true", "false"}:
            formset.add_error(None, "True/False questions must contain exactly two options: True and False.")
            return False
    return True


class QuizCatalogView(StudentRequiredMixin, ListView):
    template_name = "quiz/quiz_catalog.html"
    context_object_name = "quizzes"

    def get_queryset(self):
        now = timezone.now()
        return Quiz.objects.filter(is_published=True).filter(
            Q(start_at__isnull=True) | Q(start_at__lte=now),
            Q(end_at__isnull=True) | Q(end_at__gte=now),
        ).annotate(active_question_count=Count("questions", filter=Q(questions__is_active=True)))


class AttemptHistoryView(LoginRequiredMixin, ListView):
    template_name = "quiz/attempt_history.html"
    context_object_name = "attempts"

    def get_queryset(self):
        return (
            Attempt.objects.filter(user=self.request.user)
            .select_related("quiz", "result")
            .order_by("-started_at")
        )


class AdminQuizListView(AdminRequiredMixin, ListView):
    template_name = "quiz/admin_quiz_list.html"
    context_object_name = "quizzes"

    def get_queryset(self):
        return Quiz.objects.filter(created_by=self.request.user).annotate(
            active_question_count=Count("questions", filter=Q(questions__is_active=True))
        )


class AdminQuizCreateView(AdminRequiredMixin, CreateView):
    template_name = "quiz/admin_quiz_form.html"
    form_class = QuizForm
    success_url = reverse_lazy("quiz:admin_quiz_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Quiz created.")
        return super().form_valid(form)


class AdminQuizUpdateView(AdminRequiredMixin, UpdateView):
    template_name = "quiz/admin_quiz_form.html"
    form_class = QuizForm
    success_url = reverse_lazy("quiz:admin_quiz_list")

    def get_queryset(self):
        return Quiz.objects.filter(created_by=self.request.user)

    def form_valid(self, form):
        messages.success(self.request, "Quiz updated.")
        return super().form_valid(form)


class AdminQuizDeleteView(AdminRequiredMixin, DeleteView):
    template_name = "quiz/admin_quiz_confirm_delete.html"
    success_url = reverse_lazy("quiz:admin_quiz_list")

    def get_queryset(self):
        return Quiz.objects.filter(created_by=self.request.user)


class AdminQuestionListView(AdminRequiredMixin, TemplateView):
    template_name = "quiz/admin_question_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quiz = get_object_or_404(Quiz, pk=self.kwargs["quiz_id"], created_by=self.request.user)
        context["quiz"] = quiz
        context["questions"] = quiz.questions.prefetch_related("options")
        context["generator_form"] = QuestionGeneratorForm()
        return context


class AdminQuestionCreateView(AdminRequiredMixin, TemplateView):
    template_name = "quiz/admin_question_form.html"

    def get(self, request, *args, **kwargs):
        quiz = get_object_or_404(Quiz, pk=kwargs["quiz_id"], created_by=request.user)
        question = Question(quiz=quiz)
        context = {
            "quiz": quiz,
            "form": QuestionForm(instance=question),
            "option_formset": OptionFormSet(instance=question, prefix="options"),
            "is_create": True,
        }
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        quiz = get_object_or_404(Quiz, pk=kwargs["quiz_id"], created_by=request.user)
        question = Question(quiz=quiz)
        form = QuestionForm(request.POST, instance=question)
        formset = OptionFormSet(request.POST, instance=question, prefix="options")

        if form.is_valid() and formset.is_valid() and _validate_objective_options(form.cleaned_data["question_type"], formset):
            question = form.save(commit=False)
            question.quiz = quiz
            question.save()
            formset.instance = question
            if question.question_type in {Question.QuestionType.MCQ, Question.QuestionType.TRUE_FALSE}:
                formset.save()
            else:
                question.options.all().delete()
            messages.success(request, "Question created.")
            return redirect("quiz:admin_question_list", quiz_id=quiz.id)

        return self.render_to_response(
            {
                "quiz": quiz,
                "form": form,
                "option_formset": formset,
                "is_create": True,
            }
        )


class AdminQuestionUpdateView(AdminRequiredMixin, TemplateView):
    template_name = "quiz/admin_question_form.html"

    def get(self, request, *args, **kwargs):
        question = get_object_or_404(
            Question.objects.select_related("quiz"),
            pk=kwargs["pk"],
            quiz__created_by=request.user,
        )
        context = {
            "quiz": question.quiz,
            "question": question,
            "form": QuestionForm(instance=question),
            "option_formset": OptionFormSet(instance=question, prefix="options"),
            "is_create": False,
        }
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        question = get_object_or_404(
            Question.objects.select_related("quiz"),
            pk=kwargs["pk"],
            quiz__created_by=request.user,
        )
        form = QuestionForm(request.POST, instance=question)
        formset = OptionFormSet(request.POST, instance=question, prefix="options")

        if form.is_valid() and formset.is_valid() and _validate_objective_options(form.cleaned_data["question_type"], formset):
            question = form.save()
            if question.question_type in {Question.QuestionType.MCQ, Question.QuestionType.TRUE_FALSE}:
                formset.save()
            else:
                question.options.all().delete()
            messages.success(request, "Question updated.")
            return redirect("quiz:admin_question_list", quiz_id=question.quiz_id)

        return self.render_to_response(
            {
                "quiz": question.quiz,
                "question": question,
                "form": form,
                "option_formset": formset,
                "is_create": False,
            }
        )


class AdminQuestionDeleteView(AdminRequiredMixin, DeleteView):
    template_name = "quiz/admin_question_confirm_delete.html"
    model = Question

    def get_queryset(self):
        return Question.objects.filter(quiz__created_by=self.request.user)

    def get_success_url(self):
        messages.success(self.request, "Question deleted.")
        return reverse("quiz:admin_question_list", kwargs={"quiz_id": self.object.quiz_id})


class AdminQuestionGeneratorView(AdminRequiredMixin, View):
    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)
        form = QuestionGeneratorForm(request.POST)

        if not form.is_valid():
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            return redirect("quiz:admin_question_list", quiz_id=quiz.id)

        created = generate_questions_from_text(
            quiz=quiz,
            source_text=form.cleaned_data["source_text"],
            number_of_questions=form.cleaned_data["number_of_questions"],
            topic=form.cleaned_data["topic"],
            difficulty=int(form.cleaned_data["difficulty"]),
        )
        messages.success(request, f"Generated {created} questions.")
        return redirect("quiz:admin_question_list", quiz_id=quiz.id)


@login_required
@require_POST
def start_quiz_attempt(request, slug):
    quiz = get_object_or_404(Quiz, slug=slug)
    if not request.user.is_admin and not quiz.is_active_now():
        messages.error(request, "Quiz is not available now.")
        return redirect("quiz:catalog")

    try:
        attempt = create_attempt(request.user, quiz)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("quiz:catalog")

    return redirect("quiz:attempt_play", attempt_id=attempt.id)


class AttemptPlayView(LoginRequiredMixin, TemplateView):
    template_name = "quiz/attempt_play.html"

    def dispatch(self, request, *args, **kwargs):
        self.attempt = _get_owned_attempt(request, kwargs["attempt_id"])
        if self.attempt.status != Attempt.Status.IN_PROGRESS and not hasattr(self.attempt, "result"):
            finalize_attempt(self.attempt)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["attempt"] = self.attempt
        context["quiz"] = self.attempt.quiz
        context["remaining_seconds"] = self.attempt.time_remaining_seconds()
        context["allow_fullscreen"] = self.attempt.quiz.allow_fullscreen
        context["max_questions"] = self.attempt.max_questions
        return context


@login_required
@require_GET
def attempt_question_state(request, attempt_id, index):
    attempt = _get_owned_attempt(request, attempt_id)

    if index < 0 or index >= attempt.max_questions:
        return JsonResponse(
            {
                "completed": False,
                "error": "Question index is out of range.",
            },
            status=400,
        )

    if attempt.status != Attempt.Status.IN_PROGRESS:
        result = finalize_attempt(attempt)
        return JsonResponse(
            {
                "completed": True,
                "redirect_url": reverse("quiz:attempt_result", kwargs={"attempt_id": attempt.id}),
                "result_id": result.id,
            }
        )

    if attempt.expire_if_needed():
        finalize_attempt(attempt, force_status=Attempt.Status.EXPIRED)
        return JsonResponse(
            {
                "expired": True,
                "redirect_url": reverse("quiz:attempt_result", kwargs={"attempt_id": attempt.id}),
            }
        )

    question = get_question_for_attempt(attempt, int(index))
    if not question:
        finalize_attempt(attempt, force_status=Attempt.Status.SUBMITTED)
        return JsonResponse(
            {
                "completed": True,
                "redirect_url": reverse("quiz:attempt_result", kwargs={"attempt_id": attempt.id}),
            }
        )

    answer = AttemptAnswer.objects.filter(attempt=attempt, question=question).first()

    return JsonResponse(
        {
            "completed": False,
            "question": _serialize_question(question, answer),
            "navigation": build_navigation_payload(attempt),
            "remaining_seconds": attempt.time_remaining_seconds(),
            "current_index": int(index),
            "max_questions": attempt.max_questions,
            "allow_back_navigation": attempt.quiz.allow_back_navigation,
        }
    )


@login_required
@require_POST
def attempt_save_answer(request, attempt_id):
    attempt = _get_owned_attempt(request, attempt_id)
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return JsonResponse({"ok": False, "error": "Attempt already submitted."}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid payload."}, status=400)

    question = get_object_or_404(Question, id=data.get("question_id"), quiz=attempt.quiz)
    if not attempt.attempt_questions.filter(question=question).exists():
        return JsonResponse(
            {
                "ok": False,
                "error": "This question is not currently available in your attempt.",
            },
            status=400,
        )

    try:
        answer = save_answer(
            attempt=attempt,
            question=question,
            selected_option_id=data.get("selected_option_id"),
            text_answer=data.get("text_answer", ""),
            time_spent_seconds=data.get("time_spent_seconds", 0),
        )
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "answer_id": answer.id,
            "navigation": build_navigation_payload(attempt),
            "remaining_seconds": attempt.time_remaining_seconds(),
        }
    )


@login_required
@require_POST
def attempt_submit(request, attempt_id):
    attempt = _get_owned_attempt(request, attempt_id)
    force_status = Attempt.Status.SUBMITTED
    if attempt.expire_if_needed() or attempt.status == Attempt.Status.EXPIRED:
        force_status = Attempt.Status.EXPIRED
    result = finalize_attempt(attempt, force_status=force_status)
    return JsonResponse(
        {
            "ok": True,
            "redirect_url": reverse("quiz:attempt_result", kwargs={"attempt_id": attempt.id}),
            "result_id": result.id,
        }
    )


@login_required
@require_POST
def attempt_event(request, attempt_id):
    attempt = _get_owned_attempt(request, attempt_id)
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return JsonResponse({"ok": False, "error": "Attempt is not active."}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid payload."}, status=400)

    event_type = data.get("event_type")
    if event_type not in {"tab_switch", "fullscreen_exit"}:
        return JsonResponse({"ok": False, "error": "Unknown event type."}, status=400)

    register_anti_cheat_event(attempt, event_type)

    return JsonResponse(
        {
            "ok": True,
            "tab_switch_count": attempt.tab_switch_count,
            "full_screen_exits": attempt.full_screen_exits,
        }
    )


class AttemptResultView(LoginRequiredMixin, TemplateView):
    template_name = "quiz/attempt_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        attempt = _get_owned_attempt(self.request, kwargs["attempt_id"])
        if attempt.status == Attempt.Status.IN_PROGRESS:
            finalize_attempt(attempt)
        result = finalize_attempt(attempt)

        answers = (
            AttemptAnswer.objects.filter(attempt=attempt)
            .select_related("question", "selected_option")
            .prefetch_related("question__options")
            .order_by("question__order", "question__id")
        )

        context["attempt"] = attempt
        context["quiz"] = attempt.quiz
        context["result"] = result
        context["answers"] = answers
        return context


class StudentAnalyticsView(StudentRequiredMixin, TemplateView):
    template_name = "quiz/student_analytics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["analytics"] = get_student_analytics(self.request.user)
        return context


class AdminAnalyticsView(AdminRequiredMixin, TemplateView):
    template_name = "quiz/admin_analytics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["analytics"] = get_admin_analytics(self.request.user)
        return context


class LeaderboardView(LoginRequiredMixin, TemplateView):
    template_name = "quiz/leaderboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["leaderboard"] = get_leaderboard(limit=50)
        return context


class BadgeGalleryView(LoginRequiredMixin, TemplateView):
    template_name = "quiz/badges.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_badges"] = Badge.objects.filter(is_active=True)
        context["earned_ids"] = set(
            UserBadge.objects.filter(user=self.request.user).values_list("badge_id", flat=True)
        )
        return context


@login_required
@require_POST
def start_daily_challenge(request):
    if request.user.is_admin:
        messages.error(request, "Daily challenge is available only for students.")
        return redirect("core:dashboard")

    challenge = DailyChallenge.objects.filter(date=timezone.localdate(), is_active=True).select_related("quiz").first()
    if not challenge:
        messages.error(request, "No daily challenge available today.")
        return redirect("core:dashboard")

    try:
        attempt = create_attempt(request.user, challenge.quiz)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("core:dashboard")

    return redirect("quiz:attempt_play", attempt_id=attempt.id)


class LiveSessionCreateView(AdminRequiredMixin, CreateView):
    template_name = "quiz/live_create.html"
    form_class = LiveSessionCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.host = self.request.user
        messages.success(self.request, "Live session created.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("quiz:live_control", kwargs={"pk": self.object.pk})


class LiveSessionControlView(AdminRequiredMixin, TemplateView):
    template_name = "quiz/live_control.html"

    def get_session(self):
        return get_object_or_404(LiveQuizSession.objects.select_related("quiz"), pk=self.kwargs["pk"], host=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = self.get_session()
        context["session"] = session
        context["leaderboard"] = get_live_leaderboard(session)
        return context

    def post(self, request, *args, **kwargs):
        session = self.get_session()
        action = request.POST.get("action")

        if action == "start" and session.status == LiveQuizSession.Status.LOBBY:
            session.status = LiveQuizSession.Status.LIVE
            session.started_at = timezone.now()
            session.save(update_fields=["status", "started_at"])
        elif action == "next" and session.status == LiveQuizSession.Status.LIVE:
            session.current_question_index += 1
            total_questions = session.quiz.questions.filter(is_active=True).count()
            if session.current_question_index >= total_questions:
                session.status = LiveQuizSession.Status.ENDED
                session.ended_at = timezone.now()
                session.save(update_fields=["current_question_index", "status", "ended_at"])
            else:
                session.save(update_fields=["current_question_index"])
        elif action == "end":
            session.status = LiveQuizSession.Status.ENDED
            session.ended_at = timezone.now()
            session.save(update_fields=["status", "ended_at"])

        return redirect("quiz:live_control", pk=session.id)


class LiveSessionJoinView(LoginRequiredMixin, TemplateView):
    template_name = "quiz/live_join.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response({"form": JoinLiveSessionForm()})

    def post(self, request, *args, **kwargs):
        form = JoinLiveSessionForm(request.POST)
        if not form.is_valid():
            return self.render_to_response({"form": form})

        try:
            _session, attempt = join_live_session(request.user, form.cleaned_data["code"])
        except ValidationError as exc:
            form.add_error("code", str(exc))
            return self.render_to_response({"form": form})

        return redirect("quiz:attempt_play", attempt_id=attempt.id)


@login_required
@require_GET
def live_leaderboard_api(request, session_id):
    session = get_object_or_404(LiveQuizSession, pk=session_id)
    can_access = request.user.is_admin and session.host_id == request.user.id
    if not can_access:
        can_access = session.participants.filter(user=request.user).exists()
    if not can_access:
        raise PermissionDenied

    return JsonResponse(
        {
            "status": session.status,
            "current_question_index": session.current_question_index,
            "leaderboard": get_live_leaderboard(session),
        }
    )


@login_required
@require_GET
def export_result_pdf(request, attempt_id):
    attempt = _get_owned_attempt(request, attempt_id)
    result = finalize_attempt(attempt)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return HttpResponse("PDF export requires reportlab.", status=501)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="result_{attempt.id}.pdf"'

    pdf = canvas.Canvas(response, pagesize=A4)
    y = 800
    lines = [
        f"Quizy+ Result Summary",
        f"Student: {attempt.user.username}",
        f"Quiz: {attempt.quiz.title}",
        f"Score: {result.total_score}/{result.max_score}",
        f"Percentage: {result.percentage}%",
        f"Correct: {result.correct_count}",
        f"Wrong: {result.wrong_count}",
        f"Unattempted: {result.unattempted_count}",
        f"Generated at: {result.generated_at}",
    ]
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 24

    pdf.showPage()
    pdf.save()
    return response
