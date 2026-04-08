from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard'),

    path('groups/', views.group_list, name='group_list'),
    path('groups/create/', views.group_create, name='group_create'),
    path('groups/join/', views.join_group, name='join_group'),
    path('groups/<int:group_id>/', views.group_detail, name='group_detail'),
    path('groups/<int:group_id>/delete/', views.group_delete, name='group_delete'),
    path('groups/<int:group_id>/members/<int:user_id>/remove/', views.remove_group_member, name='remove_group_member'),

    path('groups/<int:group_id>/tasks/create/', views.task_create, name='task_create'),
    path('tasks/<int:task_id>/', views.task_detail, name='task_detail'),
    path('tasks/<int:task_id>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:task_id>/update-status/', views.update_task_status, name='update_task_status'),
    path('tasks/<int:task_id>/delete/', views.task_delete, name='task_delete'),
    path('my-tasks/', views.my_tasks, name='my_tasks'),

    path('activities/', views.activity_log, name='activity_log'),
]
