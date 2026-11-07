from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('departments/<slug:slug>/', views.department_detail_view, name='department_detail'),
    path('languages/<slug:slug>/', views.department_detail_view, name='language_landing'),
]