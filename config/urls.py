from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = 'پنل مدیریت جامع آکادمی زبان تُرنج'
admin.site.site_title = 'مدیریت تُرنج | TORANJ LMS'
admin.site.index_title = 'پیشخوان مدیریت کاربران، دوره‌ها، کلاس‌ها و تحلیل آموزشی'

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('core.urls', namespace='core')),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('dashboard/', include('dashboards.urls', namespace='dashboards')),
    path('courses/', include('courses.urls', namespace='courses')),
    path('academics/', include('academics.urls', namespace='academics')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
