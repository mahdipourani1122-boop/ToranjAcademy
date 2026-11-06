from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import ListView
from accounts.models import User
from dashboards.mixins import RoleRequiredMixin
from .models import Course, CourseCategory, ClassGroup, Enrollment
from .forms import CourseForm, ClassGroupForm
from .services import (
    ensure_default_categories,
    generate_recurring_sessions_for_class,
    assign_teacher_to_class,
    submit_student_enrollment_request,
    review_enrollment_request,
    transfer_student_enrollment,
)


class PublicCourseCatalogView(ListView):
    """کاتالوگ دوره‌های منتشرشده با جستجو، فیلتر دسته‌بندی و صفحه‌بندی"""
    model = Course
    template_name = 'courses/catalog.html'
    context_object_name = 'courses'
    paginate_by = 9

    def get_queryset(self):
        ensure_default_categories()
        qs = Course.objects.published().select_related('category').prefetch_related('classes')
        q = self.request.GET.get('q', '').strip()
        category = self.request.GET.get('category', '').strip()
        level = self.request.GET.get('level', '').strip()

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
        if category:
            qs = qs.filter(category__slug=category)
        if level:
            qs = qs.filter(language_level=level)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = CourseCategory.objects.filter(is_active=True)
        context['levels'] = Course.LanguageLevel.choices
        return context


# ==========================================
# ویوهای مدیریت دوره‌ها (مخصوص Admin)
# ==========================================
class AdminCourseCreateView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'courses/course_form.html'

    def get(self, request):
        ensure_default_categories()
        form = CourseForm()
        return render(request, self.template_name, {'form': form, 'page_title': 'ایجاد دوره آموزشی جدید'})

    def post(self, request):
        ensure_default_categories()
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.created_by = request.user
            course.save()
            messages.success(request, f'دوره «{course.title}» با موفقیت ایجاد شد.')
            return redirect('dashboards:admin')
        return render(request, self.template_name, {'form': form, 'page_title': 'ایجاد دوره آموزشی جدید'}, status=400)


class AdminCourseUpdateView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'courses/course_form.html'

    def get(self, request, course_id):
        course = get_object_or_404(Course.objects.active(), id=course_id)
        form = CourseForm(instance=course)
        return render(request, self.template_name, {'form': form, 'course': course, 'page_title': f'ویرایش دوره: {course.title}'})

    def post(self, request, course_id):
        course = get_object_or_404(Course.objects.active(), id=course_id)
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, f'تغییرات دوره «{course.title}» ذخیره شد.')
            return redirect('dashboards:admin')
        return render(request, self.template_name, {'form': form, 'course': course, 'page_title': f'ویرایش دوره: {course.title}'}, status=400)


class AdminCourseStatusActionView(RoleRequiredMixin, View):
    """انتشار، لغو انتشار، آرشیو و حذف امن (Soft Delete) دوره توسط ادمین"""
    allowed_roles = [User.Role.ADMIN]

    def post(self, request, course_id):
        course = get_object_or_404(Course.objects.active(), id=course_id)
        action = request.POST.get('action')

        if action == 'publish':
            course.publication_status = Course.PublicationStatus.PUBLISHED
            course.save(update_fields=['publication_status', 'updated_at'])
            messages.success(request, f'دوره «{course.title}» منتشر شد و اکنون برای زبان‌آموزان قابل مشاهده است.')
        elif action == 'unpublish':
            course.publication_status = Course.PublicationStatus.DRAFT
            course.save(update_fields=['publication_status', 'updated_at'])
            messages.info(request, f'دوره «{course.title}» به حالت پیش‌نویس بازگشت.')
        elif action == 'archive':
            course.publication_status = Course.PublicationStatus.ARCHIVED
            course.enrollment_status = Course.EnrollmentStatus.CLOSED
            course.save(update_fields=['publication_status', 'enrollment_status', 'updated_at'])
            messages.warning(request, f'دوره «{course.title}» آرشیو شد.')
        elif action == 'delete':
            # حفظ تاریخچه آموزشی: در صورت وجود کلاس یا ثبت‌نام، حذف نرم انجام می‌شود
            if course.classes.exists() or course.enrollments.exists():
                course.is_deleted = True
                course.deleted_at = timezone.now()
                course.publication_status = Course.PublicationStatus.ARCHIVED
                course.enrollment_status = Course.EnrollmentStatus.CLOSED
                course.save()
                messages.warning(request, f'دوره «{course.title}» دارای سابقه کلاسی بود و به صورت امن (Soft Delete) بایگانی شد.')
            else:
                title = course.title
                course.delete()
                messages.success(request, f'دوره «{title}» به طور کامل حذف شد.')

        return redirect('dashboards:admin')


# ==========================================
# ویوهای مدیریت کلاس‌ها و تخصیص استاد (Admin)
# ==========================================
class AdminClassCreateView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'courses/class_form.html'

    def get(self, request):
        form = ClassGroupForm()
        return render(request, self.template_name, {'form': form, 'page_title': 'ایجاد گروه کلاسی و زمان‌بندی جدید'})

    def post(self, request):
        form = ClassGroupForm(request.POST)
        if form.is_valid():
            class_group = form.save()
            generate_recurring_sessions_for_class(class_group)
            if class_group.teacher:
                assign_teacher_to_class(class_group, class_group.teacher, request.user, notes='تخصیص اولیه هنگام ایجاد کلاس')
            messages.success(request, f'گروه کلاسی «{class_group.name}» به همراه جلسات هفتگی ایجاد شد.')
            return redirect('dashboards:admin')
        return render(request, self.template_name, {'form': form, 'page_title': 'ایجاد گروه کلاسی و زمان‌بندی جدید'}, status=400)


class AdminClassUpdateView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'courses/class_form.html'

    def get(self, request, class_id):
        class_group = get_object_or_404(ClassGroup, id=class_id)
        form = ClassGroupForm(instance=class_group)
        return render(request, self.template_name, {'form': form, 'class_group': class_group, 'page_title': f'ویرایش کلاس: {class_group.name}'})

    def post(self, request, class_id):
        class_group = get_object_or_404(ClassGroup, id=class_id)
        form = ClassGroupForm(request.POST, instance=class_group)
        if form.is_valid():
            updated_class = form.save()
            generate_recurring_sessions_for_class(updated_class)
            messages.success(request, f'برنامه کلاس «{updated_class.name}» بروزرسانی شد.')
            return redirect('dashboards:admin')
        return render(request, self.template_name, {'form': form, 'class_group': class_group, 'page_title': f'ویرایش کلاس: {class_group.name}'}, status=400)


class AdminAssignTeacherView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]

    def post(self, request, class_id):
        class_group = get_object_or_404(ClassGroup, id=class_id)
        teacher_id = request.POST.get('teacher_id')
        teacher = get_object_or_404(User, id=teacher_id, role=User.Role.TEACHER) if teacher_id else None
        try:
            assign_teacher_to_class(class_group, teacher, request.user)
            messages.success(request, f'استاد کلاس «{class_group.name}» با موفقیت بروزرسانی شد.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect('dashboards:admin')


# ==========================================
# مشاهده لیست زبان‌آموزان کلاس (Teacher / Supervisor / Admin)
# ==========================================
class ClassRosterView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.TEACHER, User.Role.SUPERVISOR, User.Role.ADMIN]
    template_name = 'courses/class_roster.html'

    def get(self, request, class_id):
        class_group = get_object_or_404(ClassGroup.objects.select_related('course', 'teacher'), id=class_id)

        # قانون امنیتی فاز ۴: استاد فقط به کلاس‌های تخصیص‌یافته به خودش دسترسی دارد
        if request.user.role == User.Role.TEACHER and class_group.teacher_id != request.user.id:
            messages.error(request, 'دسترسی غیرمجاز: شما فقط مجاز به مشاهده لیست زبان‌آموزان کلاس‌های خودتان هستید.')
            return redirect('dashboards:teacher')

        approved_enrollments = class_group.enrollments.filter(
            status=Enrollment.Status.APPROVED
        ).select_related('student')
        sessions = class_group.sessions.all()[:20]

        return render(request, self.template_name, {
            'class_group': class_group,
            'enrollments': approved_enrollments,
            'sessions': sessions,
        })


# ==========================================
# گردش‌کار ثبت‌نام زبان‌آموز و بررسی ادمین
# ==========================================
class StudentSubmitEnrollmentView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STUDENT]

    def post(self, request, class_id):
        try:
            enrollment = submit_student_enrollment_request(student=request.user, class_group_id=class_id)
            messages.success(
                request,
                f'درخواست ثبت‌نام شما در کلاس «{enrollment.class_group.name}» ثبت شد و در انتظار تأیید مدیریت آموزش است.'
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect('dashboards:student')


class StudentCancelEnrollmentView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STUDENT]

    def post(self, request, enrollment_id):
        enrollment = get_object_or_404(Enrollment, id=enrollment_id, student=request.user)
        if enrollment.status != Enrollment.Status.PENDING:
            messages.warning(request, 'فقط درخواست‌های در انتظار تأیید توسط زبان‌آموز قابل لغو هستند.')
            return redirect('dashboards:student')

        enrollment.status = Enrollment.Status.CANCELLED
        enrollment.decision_note = 'لغو شده توسط زبان‌آموز'
        enrollment.save(update_fields=['status', 'decision_note', 'updated_at'])
        messages.info(request, 'درخواست ثبت‌نام شما لغو شد.')
        return redirect('dashboards:student')


class AdminEnrollmentReviewView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]

    def post(self, request, enrollment_id):
        action = request.POST.get('action')
        note = request.POST.get('decision_note', '').strip()
        try:
            enrollment = review_enrollment_request(enrollment_id, reviewer=request.user, action=action, note=note)
            messages.success(
                request,
                f'وضعیت ثبت‌نام «{enrollment.student.full_name}» به «{enrollment.get_status_display()}» تغییر یافت.'
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect('dashboards:admin')


class AdminManualEnrollView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]

    def post(self, request):
        student_id = request.POST.get('student')
        class_id = request.POST.get('class_group')
        student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
        try:
            submit_student_enrollment_request(
                student=student,
                class_group_id=class_id,
                by_admin=True,
                admin_user=request.user,
                auto_approve=True
            )
            messages.success(request, f'زبان‌آموز «{student.full_name}» به صورت مستقیم در کلاس ثبت‌نام شد.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect('dashboards:admin')


class AdminTransferEnrollmentView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.ADMIN]
    template_name = 'courses/transfer_form.html'

    def get(self, request, enrollment_id):
        enrollment = get_object_or_404(Enrollment.objects.select_related('student', 'class_group', 'course'), id=enrollment_id)
        available_classes = ClassGroup.objects.filter(
            is_archived=False,
            status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]
        ).exclude(id=enrollment.class_group_id)
        return render(request, self.template_name, {'enrollment': enrollment, 'available_classes': available_classes})

    def post(self, request, enrollment_id):
        new_class_id = request.POST.get('new_class_id')
        note = request.POST.get('note', '').strip()
        try:
            transfer_student_enrollment(enrollment_id, new_class_id, request.user, note=note)
            messages.success(request, 'انتقال زبان‌آموز به گروه کلاسی جدید با موفقیت انجام شد.')
            return redirect('dashboards:admin')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect('courses:enrollment_transfer', enrollment_id=enrollment_id)