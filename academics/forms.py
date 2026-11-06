from django import forms
from accounts.models import User, StudentProfile
from .models import (
    TeacherProfile,
    AcademicAssessment,
    TeacherStudentNote,
    HistoricalStudentAccess,
)

INPUT_CLS = (
    'w-full h-[42px] px-3.5 rounded-[11px] bg-toranj-inputBg border border-toranj-border '
    'text-toranj-textMain text-[13px] focus:outline-none focus:border-toranj-navy transition-all'
)
TEXTAREA_CLS = (
    'w-full p-3.5 rounded-[11px] bg-toranj-inputBg border border-toranj-border '
    'text-toranj-textMain text-[13px] focus:outline-none focus:border-toranj-navy transition-all'
)


class StudentProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(label='نام', max_length=80, widget=forms.TextInput(attrs={'class': INPUT_CLS}))
    last_name = forms.CharField(label='نام خانوادگی', max_length=80, widget=forms.TextInput(attrs={'class': INPUT_CLS}))
    email = forms.EmailField(label='ایمیل', required=False, widget=forms.EmailInput(attrs={'class': INPUT_CLS, 'dir': 'ltr'}))

    class Meta:
        model = StudentProfile
        fields = ['avatar_url', 'birth_date', 'emergency_phone', 'bio']
        widgets = {
            'avatar_url': forms.TextInput(attrs={'class': INPUT_CLS, 'dir': 'ltr'}),
            'birth_date': forms.DateInput(attrs={'class': INPUT_CLS, 'type': 'date'}),
            'emergency_phone': forms.TextInput(attrs={'class': INPUT_CLS, 'dir': 'ltr'}),
            'bio': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 2}),
        }


class TeacherProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = TeacherProfile
        fields = ['avatar_url', 'specialization', 'education_degree', 'experience_years', 'bio']
        widgets = {
            'avatar_url': forms.TextInput(attrs={'class': INPUT_CLS, 'dir': 'ltr'}),
            'specialization': forms.TextInput(attrs={'class': INPUT_CLS}),
            'education_degree': forms.TextInput(attrs={'class': INPUT_CLS}),
            'experience_years': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 0}),
            'bio': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 3}),
        }


class AssessmentWithSkillsForm(forms.ModelForm):
    speaking_score = forms.DecimalField(label='Speaking', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))
    listening_score = forms.DecimalField(label='Listening', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))
    reading_score = forms.DecimalField(label='Reading', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))
    writing_score = forms.DecimalField(label='Writing', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))
    grammar_score = forms.DecimalField(label='Grammar', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))
    vocabulary_score = forms.DecimalField(label='Vocabulary', required=False, min_value=0, max_value=100, widget=forms.NumberInput(attrs={'class': INPUT_CLS}))

    class Meta:
        model = AcademicAssessment
        fields = [
            'class_group', 'semester_label', 'title', 'assessment_type',
            'submission_status', 'score', 'max_score', 'weight', 'due_date', 'feedback'
        ]
        widgets = {
            'class_group': forms.Select(attrs={'class': INPUT_CLS}),
            'semester_label': forms.TextInput(attrs={'class': INPUT_CLS, 'placeholder': '1405-1'}),
            'title': forms.TextInput(attrs={'class': INPUT_CLS}),
            'assessment_type': forms.Select(attrs={'class': INPUT_CLS}),
            'submission_status': forms.Select(attrs={'class': INPUT_CLS}),
            'score': forms.NumberInput(attrs={'class': INPUT_CLS, 'step': '0.25'}),
            'max_score': forms.NumberInput(attrs={'class': INPUT_CLS, 'step': '0.25'}),
            'weight': forms.NumberInput(attrs={'class': INPUT_CLS, 'step': '0.1'}),
            'due_date': forms.DateInput(attrs={'class': INPUT_CLS, 'type': 'date'}),
            'feedback': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 2}),
        }


class TeacherNoteForm(forms.ModelForm):
    class Meta:
        model = TeacherStudentNote
        fields = ['class_group', 'note_text', 'recommendation', 'is_private_to_staff']
        widgets = {
            'class_group': forms.Select(attrs={'class': INPUT_CLS}),
            'note_text': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 2}),
            'recommendation': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 2}),
            'is_private_to_staff': forms.CheckboxInput(attrs={'class': 'w-4 h-4 rounded border-toranj-border text-toranj-navy'}),
        }


class HistoricalAccessGrantForm(forms.ModelForm):
    class Meta:
        model = HistoricalStudentAccess
        fields = ['teacher', 'student', 'reason', 'expires_at']
        widgets = {
            'teacher': forms.Select(attrs={'class': INPUT_CLS}),
            'student': forms.Select(attrs={'class': INPUT_CLS}),
            'reason': forms.TextInput(attrs={'class': INPUT_CLS}),
            'expires_at': forms.DateTimeInput(attrs={'class': INPUT_CLS, 'type': 'datetime-local'}),
        }
