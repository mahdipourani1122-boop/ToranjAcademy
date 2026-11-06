from accounts.models import User
from courses.models import ClassGroup, Enrollment
from .models import HistoricalStudentAccess


def get_teacher_current_student_ids(teacher: User) -> set:
    if teacher.role != User.Role.TEACHER:
        return set()
    return set(
        Enrollment.objects.filter(
            class_group__teacher=teacher,
            class_group__is_archived=False,
            class_group__status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE],
            status=Enrollment.Status.APPROVED,
        ).values_list('student_id', flat=True)
    )


def get_teacher_historical_authorized_student_ids(teacher: User) -> set:
    if teacher.role != User.Role.TEACHER:
        return set()
    grants = HistoricalStudentAccess.objects.filter(teacher=teacher, is_active=True)
    return {g.student_id for g in grants if g.is_valid}


def can_user_view_student_academic_profile(viewer: User, target_student: User) -> tuple[bool, str]:
    if not viewer or not viewer.is_authenticated or not viewer.is_active:
        return False, 'unauthenticated'

    if target_student.role != User.Role.STUDENT:
        return False, 'invalid_target'

    if viewer.role == User.Role.STUDENT:
        if viewer.id == target_student.id:
            return True, 'self_student'
        return False, 'student_idor_blocked'

    if viewer.role == User.Role.TEACHER:
        if target_student.id in get_teacher_current_student_ids(viewer):
            return True, 'assigned_teacher'
        if target_student.id in get_teacher_historical_authorized_student_ids(viewer):
            return True, 'historical_authorized_teacher'
        return False, 'teacher_unauthorized_student'

    if viewer.role in [User.Role.ADMIN, User.Role.SUPERVISOR]:
        return True, 'staff_admin'

    return False, 'denied'
