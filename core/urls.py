from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('news/', views.news_list_view, name='news_list'),
    path('guest-explore/', views.guest_explore_view, name='guest_explore'),
    path('departments/<slug:slug>/', views.department_detail_view, name='department_detail'),
    path('languages/<slug:slug>/', views.department_detail_view, name='language_landing'),
]
