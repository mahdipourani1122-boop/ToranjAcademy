from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'phone', 'role', 'status', 'created_at')
    list_filter = ('role', 'status', 'is_staff', 'created_at')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_login')

    fieldsets = (
        ('اطلاعات ورود', {'fields': ('id', 'email', 'password')}),
        ('اطلاعات هویتی', {'fields': ('first_name', 'last_name', 'phone', 'accepted_terms')}),
        ('نقش و کنترل دسترسی (فقط مدیر ارشد)', {'fields': ('role', 'status', 'is_active', 'is_staff', 'is_superuser')}),
        ('گزارش زمانی', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone', 'role', 'status', 'password1', 'password2'),
        }),
    )