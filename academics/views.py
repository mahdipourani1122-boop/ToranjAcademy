from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

from accounts.models import User, StudentProfile, SecurityEvent
from accounts.security import log_security_event
from courses.models import ClassGroup, ClassSession, Enrollment
from dashboards.mixins import RoleRequiredMixin

from .models import (
    TeacherProfile,
    AttendanceRecord,
    SkillAssessmentScore,
    TeacherStudentNote,
    HistoricalStudentAccess,
)
from .analytics import compute_student_academic_analytics, compute_class_and_teacher_performance_summary
from .ai_advisor import generate_grounded_ai_recommendations
from .permissions import (
    can_user_view_student_academic_profile,
    get_teacher_current_student_ids,
    get_teacher_historical_authorized_student_ids,
)
from .forms import (
    StudentProfileUpdateForm,
    TeacherProfileUpdateForm,
    AssessmentWithSkillsForm,
    TeacherNoteForm,
    HistoricalAccessGrantForm,
)


class MyAcademicProfileRedirectView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.role == User.Role.STUDENT:
            return redirect('academics:student_profile', student_id=request.user.id)
        if request.user.role == User.Role.TEACHER:
            return redirect('academics:teacher_profile', teacher_id=request.user.id)
        return redirect('academics:admin_hub')


class StudentUnifiedProfileView(LoginRequiredMixin, View):
    template_name = 'academics/student_profile.html'

    def get(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        allowed, access_mode = can_user_view_student_academic_profile(request.user, target_student)

        if not allowed:
            log_security_event(
                request,
                event_type='UNAUTHORIZED_PROFILE_ACCESS',
                description=f"تلاش غیرمجاز برای مشاهده پرونده زبان‌آموز {target_student.id}",
                user=request.user,
                severity=SecurityEvent.Severity.WARNING
            )
            return HttpResponseForbidden('دسترسی غیرمجاز (403 Forbidden): شما مجاز به مشاهده این پرونده نیستید.')

        profile, _ = StudentProfile.objects.get_or_create(user=target_student)
        semester_filter = request.GET.get('semester', '').strip() or None

        analytics = compute_student_academic_analytics(target_student, semester_filter=semester_filter)
        ai_recommendations = generate_grounded_ai_recommendations(analytics)

        enrollments = Enrollment.objects.filter(student=target_student).select_related(
            'course', 'class_group', 'class_group__teacher'
        ).order_by('-requested_at')
        current_enrollments = enrollments.filter(
            status=Enrollment.Status.APPROVED,
            class_group__status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]
        )
        previous_enrollments = enrollments.exclude(id__in=current_enrollments.values_list('id', flat=True))

        is_staff_viewer = request.user.role in [User.Role.TEACHER, User.Role.SUPERVISOR, User.Role.ADMIN]
        if is_staff_viewer:
            teacher_notes = TeacherStudentNote.objects.filter(student=target_student).select_related('author', 'class_group')
        else:
            teacher_notes = TeacherStudentNote.objects.filter(
                student=target_student,
                is_private_to_staff=False
            ).select_related('author', 'class_group')

        assessment_form = AssessmentWithSkillsForm()
        note_form = TeacherNoteForm()
        if request.user.role == User.Role.TEACHER:
            teacher_classes = ClassGroup.objects.filter(teacher=request.user, is_archived=False)
            assessment_form.fields['class_group'].queryset = teacher_classes
            note_form.fields['class_group'].queryset = teacher_classes

        profile_form = StudentProfileUpdateForm(
            instance=profile,
            initial={
                'first_name': target_student.first_name,
                'last_name': target_student.last_name,
                'email': target_student.email,
            }
        ) if (request.user.id == target_student.id or request.user.role == User.Role.ADMIN) else None

        return render(request, self.template_name, {
            'target_student': target_student,
            'student_profile': profile,
            'access_mode': access_mode,
            'is_staff_viewer': is_staff_viewer,
            'can_record_academic_data': request.user.role in [User.Role.TEACHER, User.Role.ADMIN],
            'analytics': analytics,
            'ai_recommendations': ai_recommendations,
            'current_enrollments': current_enrollments,
            'previous_enrollments': previous_enrollments,
            'teacher_notes': teacher_notes,
            'assessment_form': assessment_form,
            'note_form': note_form,
            'profile_form': profile_form,
        })

    def post(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        if request.user.id != target_student.id and request.user.role != User.Role.ADMIN:
            return HttpResponseForbidden('دسترسی غیرمجاز برای ویرایش پروفایل.')

        profile, _ = StudentProfile.objects.get_or_create(user=target_student)
        form = StudentProfileUpdateForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            target_student.first_name = form.cleaned_data['first_name'].strip()
            target_student.last_name = form.cleaned_data['last_name'].strip()
            target_student.email = form.cleaned_data.get('email') or None
            target_student.save(update_fields=['first_name', 'last_name', 'email', 'updated_at'])
            messages.success(request, 'اطلاعات پروفایل با موفقیت بروزرسانی شد.')
        return redirect('academics:student_profile', student_id=target_student.id)


class RecordStudentAssessmentView(LoginRequiredMixin, View):
    @transaction.atomic
    def post(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        allowed, _ = can_user_view_student_academic_profile(request.user, target_student)
        if not allowed or request.user.role not in [User.Role.TEACHER, User.Role.ADMIN]:
            return HttpResponseForbidden('شما مجوز ثبت نمره برای این زبان‌آموز را ندارید.')

        form = AssessmentWithSkillsForm(request.POST)
        if form.is_valid():
            class_group = form.cleaned_data['class_group']
            if request.user.role == User.Role.TEACHER and class_group.teacher_id != request.user.id:
                return HttpResponseForbidden('شما فقط مجاز به ثبت نمره برای کلاس‌های خودتان هستید.')

            assessment = form.save(commit=False)
            assessment.student = target_student
            assessment.evaluated_by = request.user
            enrollment = Enrollment.objects.filter(student=target_student, class_group=class_group).first()
            assessment.enrollment = enrollment
            assessment.save()

            skill_map = {
                'speaking': form.cleaned_data.get('speaking_score'),
                'listening': form.cleaned_data.get('listening_score'),
                'reading': form.cleaned_data.get('reading_score'),
                'writing': form.cleaned_data.get('writing_score'),
                'grammar': form.cleaned_data.get('grammar_score'),
                'vocabulary': form.cleaned_data.get('vocabulary_score'),
            }
            for skill_key, val in skill_map.items():
                if val is not None:
                    SkillAssessmentScore.objects.update_or_create(
                        assessment=assessment,
                        skill=skill_key,
                        defaults={'score': val}
                    )
            messages.success(request, f'ارزیابی «{assessment.title}» ثبت شد.')
        return redirect('academics:student_profile', student_id=target_student.id)


class RecordStudentNoteView(LoginRequiredMixin, View):
    def post(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        allowed, _ = can_user_view_student_academic_profile(request.user, target_student)
        if not allowed or request.user.role not in [User.Role.TEACHER, User.Role.ADMIN]:
            return HttpResponseForbidden('شما مجوز ثبت یادداشت برای این زبان‌آموز را ندارید.')

        form = TeacherNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.student = target_student
            note.author = request.user
            note.save()
            messages.success(request, 'یادداشت آموزشی ثبت شد.')
        return redirect('academics:student_profile', student_id=target_student.id)


class RecordStudentAttendanceQuickView(LoginRequiredMixin, View):
    def post(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        allowed, _ = can_user_view_student_academic_profile(request.user, target_student)
        if not allowed or request.user.role not in [User.Role.TEACHER, User.Role.ADMIN]:
            return HttpResponseForbidden('دسترسی غیرمجاز.')

        session_id = request.POST.get('session_id')
        status_val = request.POST.get('status', AttendanceRecord.Status.PRESENT)
        delay = int(request.POST.get('delay_minutes') or 0)
        note = (request.POST.get('note') or '').strip()

        session = get_object_or_404(ClassSession.objects.select_related('class_group'), id=session_id)
        if request.user.role == User.Role.TEACHER and session.class_group.teacher_id != request.user.id:
            return HttpResponseForbidden('دسترسی غیرمجاز.')

        AttendanceRecord.objects.update_or_create(
            session=session,
            student=target_student,
            defaults={'status': status_val, 'delay_minutes': delay, 'recorded_by': request.user, 'note': note}
        )
        return redirect('academics:student_profile', student_id=target_student.id)


class StudentProgressReportView(LoginRequiredMixin, View):
    template_name = 'academics/student_progress_report.html'

    def get(self, request, student_id):
        target_student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        allowed, _ = can_user_view_student_academic_profile(request.user, target_student)
        if not allowed:
            return HttpResponseForbidden('دسترسی غیرمجاز.')

        semester_filter = request.GET.get('semester', '').strip() or None
        analytics = compute_student_academic_analytics(target_student, semester_filter=semester_filter)
        ai_recommendations = generate_grounded_ai_recommendations(analytics)
        public_notes = TeacherStudentNote.objects.filter(
            student=target_student, is_private_to_staff=False
        ).select_related('author', 'class_group')

        return render(request, self.template_name, {
            'target_student': target_student,
            'analytics': analytics,
            'ai_recommendations': ai_recommendations,
            'public_notes': public_notes,
        })


class TeacherUnifiedProfileView(LoginRequiredMixin, View):
    template_name = 'academics/teacher_profile.html'

    def get(self, request, teacher_id):
        target_teacher = get_object_or_404(User, id=teacher_id, role=User.Role.TEACHER)
        if request.user.role == User.Role.STUDENT or (
            request.user.role == User.Role.TEACHER and request.user.id != target_teacher.id
        ):
            return HttpResponseForbidden('دسترسی غیرمجاز.')

        t_profile, _ = TeacherProfile.objects.get_or_create(user=target_teacher)
        assigned_classes = ClassGroup.objects.filter(
            teacher=target_teacher, is_archived=False
        ).select_related('course', 'classroom')

        current_student_ids = get_teacher_current_student_ids(target_teacher)
        historical_student_ids = get_teacher_historical_authorized_student_ids(target_teacher)

        current_students = User.objects.filter(id__in=current_student_ids, role=User.Role.STUDENT)
        historical_students = User.objects.filter(
            id__in=(historical_student_ids - current_student_ids),
            role=User.Role.STUDENT
        )

        current_students_analytics = [
            {'student': s, 'summary': compute_student_academic_analytics(s)}
            for s in current_students
        ]
        historical_students_analytics = [
            {'student': s, 'summary': compute_student_academic_analytics(s)}
            for s in historical_students
        ]

        return render(request, self.template_name, {
            'target_teacher': target_teacher,
            'teacher_profile': t_profile,
            'assigned_classes': assigned_classes,
            'current_students_analytics': current_students_analytics,
            'historical_students_analytics': historical_students_analytics,
        })


class AdminAcademicAnalyticsHubView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN, User.Role.SUPERVISOR]
    template_name = 'academics/admin_analytics_hub.html'

    def get(self, request):
        q = request.GET.get('q', '').strip()
        semester_filter = request.GET.get('semester', '').strip()
        support_only = request.GET.get('support_only') == '1'

        students_qs = User.objects.filter(role=User.Role.STUDENT).select_related('student_profile')
        if q:
            students_qs = students_qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(academy_username__icontains=q)
                | Q(phone__icontains=q)
            )

        student_rows = []
        at_risk_count = 0
        for st in students_qs[:60]:
            summary = compute_student_academic_analytics(st, semester_filter=semester_filter or None)
            if summary['needs_academic_support']:
                at_risk_count += 1
            if support_only and not summary['needs_academic_support']:
                continue
            student_rows.append({'student': st, 'analytics': summary})

        class_reports = compute_class_and_teacher_performance_summary()
        active_grants = HistoricalStudentAccess.objects.filter(is_active=True).select_related('teacher', 'student', 'granted_by')

        grant_form = HistoricalAccessGrantForm()
        grant_form.fields['teacher'].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        grant_form.fields['student'].queryset = User.objects.filter(role=User.Role.STUDENT, is_active=True)

        return render(request, self.template_name, {
            'student_rows': student_rows,
            'at_risk_count': at_risk_count,
            'class_reports': class_reports,
            'active_grants': active_grants,
            'grant_form': grant_form,
            'q': q,
            'semester_filter': semester_filter,
            'support_only': support_only,
        })

    def post(self, request):
        if request.user.role != User.Role.ADMIN:
            return HttpResponseForbidden('فقط مدیر کل مجاز است.')

        action = request.POST.get('action')
        if action == 'grant_historical_access':
            form = HistoricalAccessGrantForm(request.POST)
            if form.is_valid():
                teacher = form.cleaned_data['teacher']
                student = form.cleaned_data['student']
                HistoricalStudentAccess.objects.update_or_create(
                    teacher=teacher,
                    student=student,
                    defaults={
                        'granted_by': request.user,
                        'reason': form.cleaned_data['reason'],
                        'expires_at': form.cleaned_data.get('expires_at'),
                        'is_active': True,
                    }
                )
                messages.success(request, 'مجوز دسترسی صادر شد.')
        elif action == 'revoke_historical_access':
            grant_id = request.POST.get('grant_id')
            grant = get_object_or_404(HistoricalStudentAccess, id=grant_id)
            grant.is_active = False
            grant.save(update_fields=['is_active'])
            messages.info(request, 'مجوز دسترسی لغو شد.')

        return redirect('academics:admin_hub')
