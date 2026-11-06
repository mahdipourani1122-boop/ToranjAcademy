from django import forms
from accounts.models import User
from .models import Course, ClassGroup, Classroom

INPUT_CLS = (
    'w-full h-[44px] px-3.5 rounded-[11px] bg-toranj-inputBg border border-toranj-border '
    'text-toranj-textMain text-[14px] focus:outline-none focus:border-toranj-navy transition-all'
)
TEXTAREA_CLS = (
    'w-full p-3.5 rounded-[11px] bg-toranj-inputBg border border-toranj-border '
    'text-toranj-textMain text-[14px] focus:outline-none focus:border-toranj-navy transition-all'
)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'title', 'category', 'age_group', 'language_level',
            'course_type', 'course_format', 'tuition_fee',
            'duration_weeks', 'sessions_count', 'min_capacity', 'max_capacity',
            'enrollment_status', 'publication_status', 'cover_image',
            'description', 'learning_objectives',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLS, 'placeholder': 'مثال: دوره جامع مکالمه بزرگسالان (سطح B1)'}),
            'category': forms.Select(attrs={'class': INPUT_CLS}),
            'age_group': forms.Select(attrs={'class': INPUT_CLS}),
            'language_level': forms.Select(attrs={'class': INPUT_CLS}),
            'course_type': forms.Select(attrs={'class': INPUT_CLS}),
            'course_format': forms.Select(attrs={'class': INPUT_CLS}),
            'tuition_fee': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 0}),
            'duration_weeks': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 1}),
            'sessions_count': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 1}),
            'min_capacity': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 1}),
            'max_capacity': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 1}),
            'enrollment_status': forms.Select(attrs={'class': INPUT_CLS}),
            'publication_status': forms.Select(attrs={'class': INPUT_CLS}),
            'cover_image': forms.TextInput(attrs={'class': INPUT_CLS, 'dir': 'ltr', 'placeholder': 'https://...'}),
            'description': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 3}),
            'learning_objectives': forms.Textarea(attrs={'class': TEXTAREA_CLS, 'rows': 3}),
        }


class ClassGroupForm(forms.ModelForm):
    selected_days = forms.MultipleChoiceField(
        label='روزهای برگزاری در هفته',
        choices=ClassGroup.DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'rounded border-toranj-border text-toranj-navy'}),
        required=True,
        error_messages={'required': 'انتخاب حداقل یک روز در هفته الزامی است.'}
    )

    class Meta:
        model = ClassGroup
        fields = [
            'course', 'name', 'code', 'teacher', 'classroom',
            'start_date', 'end_date', 'start_time', 'end_time',
            'max_capacity', 'class_format', 'location_or_link',
            'enrollment_status', 'status',
        ]
        widgets = {
            'course': forms.Select(attrs={'class': INPUT_CLS}),
            'name': forms.TextInput(attrs={'class': INPUT_CLS, 'placeholder': 'مثال: گروه الف - شنبه و دوشنبه'}),
            'code': forms.TextInput(attrs={'class': INPUT_CLS, 'dir': 'ltr', 'placeholder': 'TRJ-B1-101'}),
            'teacher': forms.Select(attrs={'class': INPUT_CLS}),
            'classroom': forms.Select(attrs={'class': INPUT_CLS}),
            'start_date': forms.DateInput(attrs={'class': INPUT_CLS, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': INPUT_CLS, 'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'class': INPUT_CLS, 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': INPUT_CLS, 'type': 'time'}),
            'max_capacity': forms.NumberInput(attrs={'class': INPUT_CLS, 'min': 1}),
            'class_format': forms.Select(attrs={'class': INPUT_CLS}),
            'location_or_link': forms.TextInput(attrs={'class': INPUT_CLS, 'placeholder': 'کلاس ۲۰۲ یا لینک اتاق آنلاین'}),
            'enrollment_status': forms.Select(attrs={'class': INPUT_CLS}),
            'status': forms.Select(attrs={'class': INPUT_CLS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.active()
        self.fields['teacher'].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        self.fields['classroom'].queryset = Classroom.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.days_of_week:
            self.initial['selected_days'] = self.instance.days_list

    def clean(self):
        cleaned_data = super().clean()
        days = cleaned_data.get('selected_days')
        if days:
            self.instance.days_of_week = ','.join(days)
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.days_of_week = ','.join(self.cleaned_data.get('selected_days', []))
        if commit:
            instance.save()
        return instance


class AdminManualEnrollmentForm(forms.Form):
    student = forms.ModelChoiceField(
        label='انتخاب زبان‌آموز',
        queryset=User.objects.filter(role=User.Role.STUDENT, is_active=True),
        widget=forms.Select(attrs={'class': INPUT_CLS})
    )
    class_group = forms.ModelChoiceField(
        label='انتخاب گروه کلاسی',
        queryset=ClassGroup.objects.filter(is_archived=False, status__in=['planned', 'active']),
        widget=forms.Select(attrs={'class': INPUT_CLS})
    )