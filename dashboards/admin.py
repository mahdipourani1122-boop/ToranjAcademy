from django.contrib import admin
from .models import (
    AttendancePolicy,
    AttendanceSession,
    AttendanceEntry,
    AttendanceAuditLog,
    AttendanceNotification,
)


@admin.register(AttendancePolicy)
class AttendancePolicyAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_academy_default', 'course_id', 'teacher_approval_deadline_hours', 'require_online_code', 'updated_at')
    list_filter = ('is_academy_default', 'require_online_code')


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ('course_title', 'title', 'mode', 'session_date', 'teacher', 'status', 'is_finalized')
    list_filter = ('mode', 'status', 'is_finalized', 'department')
    search_fields = ('course_title', 'title')


@admin.register(AttendanceEntry)
class AttendanceEntryAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'attendance_method', 'requested_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'attendance_method')


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'action', 'actor', 'actor_role', 'student', 'previous_status', 'new_status', 'reason')
    readonly_fields = ('session', 'entry', 'student', 'actor', 'actor_role', 'action', 'previous_status', 'new_status', 'reason', 'ip_address', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False