from django.contrib import admin
from .models import Group, Task, ActivityLog

# Register your models here.

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_by', 'get_member_count', 'created_at']
    search_fields = ['name', 'description']
    filter_horizontal = ['members']

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'group', 'assigned_to', 'status', 'deadline']
    list_filter = ['status', 'group', 'created_at']
    search_fields = ['title', 'description']

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'group', 'task', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['description']