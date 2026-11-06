from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import redirect, get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from accounts.models import User
from courses.models import Course, ClassGroup, Enrollment
from courses.forms import AdminManualEnrollmentForm
from courses.services import ensure_default_categories
from .mixins import RoleRequiredMixin


class DashboardRedirectView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return redirect(request.user.get_dashboard_url_name())


class StudentDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = [User.Role.STUDENT]
    template_name = 'dashboards/student.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ensure_default_categories()
        student = self.request.user

        context['panel_title'] = 'پنل کاربری زبان‌آموز'
        context['panel_subtitle'] = 'انتخاب دوره، پیگیری درخواست‌های ثبت‌نام و مشاهده برنامه کلاسی'
        context['role_badge'] = 'زبان‌آموز'

        my_enrollments = Enrollment.objects.filter(student=student).select_related(
            'course', 'class_group', 'class_group__teacher'
        )
        approved_enrollments = my_enrollments.filter(status=Enrollment.Status.APPROVED)
        pending_enrollments = my_enrollments.filter(status=Enrollment.Status.PENDING)

        # دوره‌های منتشرشده و کلاس‌های باز برای ثبت‌نام
        available_classes = ClassGroup.objects.filter(
            is_archived=False,
            status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE],
            enrollment_status=ClassGroup.EnrollmentStatus.OPEN,
            course__is_deleted=False,
            course__publication_status=Course.PublicationStatus.PUBLISHED,
            course__enrollment_status=Course.EnrollmentStatus.OPEN,
        ).select_related('course', 'course__category', 'teacher')

        context['nav_items'] = [
            {'id': 'overview', 'label': 'داشبورد', 'icon': 'layout-dashboard', 'active': True},
            {'id': 'available-courses', 'label': 'انتخاب دوره و ثبت‌نام', 'icon': 'sparkles', 'badge': str(available_classes.count())},
            {'id': 'my-enrollments', 'label': 'درخواست‌های ثبت‌نام من', 'icon': 'file-clock', 'badge': str(pending_enrollments.count()) if pending_enrollments.exists() else ''},
            {'id': 'approved-courses', 'label': 'کلاس‌های تاییدشده من', 'icon': 'book-open', 'badge': str(approved_enrollments.count())},
            {'id': 'schedule', 'label': 'برنامه هفتگی کلاس‌ها', 'icon': 'calendar-days'},
            {'id': 'profile', 'label': 'پروفایل زبان‌آموز', 'icon': 'user-cog'},
        ]

        context['my_enrollments'] = my_enrollments
        context['approved_enrollments'] = approved_enrollments
        context['pending_enrollments'] = pending_enrollments
        context['available_classes'] = available_classes

        context['notifications'] = [
            {'title': f'{approved_enrollments.count()} کلاس فعال در برنامه شما ثبت شده است', 'time': 'هم‌اکنون', 'type': 'success'},
        ]
        if pending_enrollments.exists():
            context['notifications'].append({
                'title': f'{pending_enrollments.count()} درخواست ثبت‌نام در انتظار بررسی مدیریت است',
                'time': 'در جریان',
                'type': 'warning'
            })
        return context


class TeacherDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = [User.Role.TEACHER]
    template_name = 'dashboards/teacher.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        teacher = self.request.user

        # قانون امنیتی فاز ۴: استاد فقط کلاس‌های تخصیص‌یافته به خودش را می‌بیند
        assigned_classes = ClassGroup.objects.filter(
            teacher=teacher,
            is_archived=False
        ).select_related('course', 'classroom').prefetch_related('enrollments__student')

        context['panel_title'] = 'پنل آموزشی استاد'
        context['panel_subtitle'] = 'مشاهده کلاس‌های تخصیص‌یافته، برنامه هفتگی تدریس و لیست زبان‌آموزان'
        context['role_badge'] = 'استاد'

        context['nav_items'] = [
            {'id': 'overview', 'label': 'میز کار استاد', 'icon': 'layout-dashboard', 'active': True},
            {'id': 'classes', 'label': 'کلاس‌های من', 'icon': 'presentation', 'badge': str(assigned_classes.count())},
            {'id': 'schedule', 'label': 'برنامه هفتگی تدریس', 'icon': 'calendar-days'},
        ]

        context['assigned_classes'] = assigned_classes
        context['active_classes_count'] = assigned_classes.filter(
            status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]
        ).count()
        context['notifications'] = [
            {'title': f'{context["active_classes_count"]} گروه کلاسی فعال به شما تخصیص یافته است', 'time': 'به‌روز', 'type': 'info'}
        ]
        return context


class SupervisorDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = [User.Role.SUPERVISOR]
    template_name = 'dashboards/supervisor.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['panel_title'] = 'پنل نظارت و سوپروایزر آموزشی'
        context['panel_subtitle'] = 'پایش جامع کلاس‌ها، برنامه اساتید و بررسی وضعیت ثبت‌نام زبان‌آموزان'
        context['role_badge'] = 'سوپروایزر'

        all_classes = ClassGroup.objects.filter(is_archived=False).select_related('course', 'teacher', 'classroom')
        all_enrollments = Enrollment.objects.select_related('student', 'course', 'class_group', 'reviewed_by')[:30]
        teachers_workload = User.objects.filter(role=User.Role.TEACHER, is_active=True).annotate(
            active_classes_count=Count(
                'assigned_classes',
                filter=Q(assigned_classes__status__in=['planned', 'active'], assigned_classes__is_archived=False)
            )
        )

        context['nav_items'] = [
            {'id': 'overview', 'label': 'داشبورد نظارتی', 'icon': 'layout-dashboard', 'active': True},
            {'id': 'classes', 'label': 'پایش کلاس‌ها و ظرفیت', 'icon': 'activity', 'badge': str(all_classes.count())},
            {'id': 'teachers', 'label': 'بار آموزشی اساتید', 'icon': 'award'},
            {'id': 'enrollments', 'label': 'وضعیت ثبت‌نام‌ها', 'icon': 'clipboard-check'},
        ]

        context['all_classes'] = all_classes
        context['all_enrollments'] = all_enrollments
        context['teachers_workload'] = teachers_workload
        context['pending_enrollments_count'] = Enrollment.objects.filter(status=Enrollment.Status.PENDING).count()
        return context


class AdminDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'dashboards/admin.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ensure_default_categories()

        context['panel_title'] = 'پنل مدیریت کل آکادمی زبان تُرنج'
        context['panel_subtitle'] = 'مدیریت دوره‌ها، زمان‌بندی کلاس‌ها، تخصیص اساتید، ثبت‌نام‌ها و نقش‌های کاربری'
        context['role_badge'] = 'مدیر ارشد'

        courses_qs = Course.objects.active().select_related('category')
        classes_qs = ClassGroup.objects.filter(is_archived=False).select_related('course', 'teacher', 'classroom')
        enrollments_qs = Enrollment.objects.select_related('student', 'course', 'class_group', 'reviewed_by')
        pending_enrollments = enrollments_qs.filter(status=Enrollment.Status.PENDING)

        teachers_qs = User.objects.filter(role=User.Role.TEACHER, is_active=True).annotate(
            active_classes_count=Count(
                'assigned_classes',
                filter=Q(assigned_classes__status__in=['planned', 'active'], assigned_classes__is_archived=False)
            )
        )

        context['nav_items'] = [
            {'id': 'overview', 'label': 'پیشخوان مدیریت', 'icon': 'layout-dashboard', 'active': True},
            {'id': 'enrollments', 'label': 'درخواست‌های ثبت‌نام', 'icon': 'user-check', 'badge': str(pending_enrollments.count()) if pending_enrollments.exists() else ''},
            {'id': 'courses', 'label': 'مدیریت دوره‌ها', 'icon': 'book-open', 'badge': str(courses_qs.count())},
            {'id': 'classes', 'label': 'کلاس‌ها و تخصیص استاد', 'icon': 'calendar', 'badge': str(classes_qs.count())},
            {'id': 'teachers', 'label': 'برنامه و بار کاری اساتید', 'icon': 'graduation-cap'},
            {'id': 'users', 'label': 'کاربران و نقش‌ها (RBAC)', 'icon': 'shield-check'},
        ]

        context['courses'] = courses_qs
        context['classes'] = classes_qs
        context['enrollments'] = enrollments_qs[:40]
        context['pending_enrollments_count'] = pending_enrollments.count()
        context['teachers'] = teachers_qs
        context['manual_enroll_form'] = AdminManualEnrollmentForm()

        users_qs = User.objects.all().order_by('-created_at')
        context['total_users_count'] = users_qs.count()
        context['students_count'] = users_qs.filter(role=User.Role.STUDENT).count()
        context['teachers_count'] = users_qs.filter(role=User.Role.TEACHER).count()
        context['recent_users'] = users_qs[:20]
        context['role_choices'] = User.Role.choices
        context['status_choices'] = User.Status.choices

        context['notifications'] = [
            {'title': f'{pending_enrollments.count()} درخواست ثبت‌نام منتظر تأیید شماست', 'time': 'فوری', 'type': 'warning'},
            {'title': f'{courses_qs.filter(publication_status="published").count()} دوره منتشرشده فعال است', 'time': 'سیستم', 'type': 'success'},
        ]
        return context


class AdminUpdateUserRoleView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]

    def post(self, request, user_id):
        target_user = get_object_or_404(User, id=user_id)
        new_role = request.POST.get('role')
        new_status = request.POST.get('status')

        if new_role not in dict(User.Role.choices) or new_status not in dict(User.Status.choices):
            messages.error(request, 'مقادیر ارسالی معتبر نیست.')
            return redirect('dashboards:admin')

        if target_user.id == request.user.id and (new_role != User.Role.ADMIN or new_status != User.Status.ACTIVE):
            messages.warning(request, 'نمی‌توانید نقش مدیریت یا وضعیت فعال حساب خودتان را غیرفعال کنید.')
            return redirect('dashboards:admin')

        target_user.role = new_role
        target_user.status = new_status
        target_user.is_active = (new_status != User.Status.SUSPENDED)
        target_user.save(update_fields=['role', 'status', 'is_active', 'updated_at'])
        messages.success(request, f'نقش کاربر «{target_user.full_name}» به «{target_user.get_role_display()}» تغییر یافت.')
        return redirect('dashboards:admin')