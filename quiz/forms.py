from django import forms

from .models import LiveQuizSession, Option, Question, Quiz


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = [
            "title",
            "slug",
            "description",
            "category",
            "time_limit_minutes",
            "passing_percentage",
            "negative_marking_percentage",
            "shuffle_questions",
            "allow_back_navigation",
            "allow_fullscreen",
            "is_adaptive",
            "is_published",
            "is_daily_challenge",
            "start_at",
            "end_at",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = [
            "question_type",
            "prompt",
            "answer_key",
            "explanation",
            "topic",
            "difficulty",
            "marks",
            "order",
            "is_active",
        ]
        widgets = {
            "prompt": forms.Textarea(attrs={"rows": 3}),
            "explanation": forms.Textarea(attrs={"rows": 2}),
        }


class OptionForm(forms.ModelForm):
    class Meta:
        model = Option
        fields = ["text", "is_correct", "order"]


class QuestionGeneratorForm(forms.Form):
    source_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}))
    number_of_questions = forms.IntegerField(min_value=1, max_value=20, initial=5)
    topic = forms.CharField(max_length=120, initial="Generated Topic")
    difficulty = forms.ChoiceField(choices=Question.Difficulty.choices)


class LiveSessionCreateForm(forms.ModelForm):
    class Meta:
        model = LiveQuizSession
        fields = ["quiz", "reveal_answers"]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["quiz"].queryset = Quiz.objects.filter(created_by=user, is_published=True)


class JoinLiveSessionForm(forms.Form):
    code = forms.CharField(max_length=8)
