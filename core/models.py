from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
import random
import string


def generate_join_code(length=8):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=length))

class Group(models.Model):
    """Project group model"""
    name = models.CharField(max_length=200)
    join_code = models.CharField(
        max_length=8,
        unique=True,
        editable=False,
        default=generate_join_code,
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_groups')
    members = models.ManyToManyField(User, related_name='custom_groups')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('group_detail', args=[self.id])
    
    def get_member_count(self):
        return self.members.count()
    
    def get_completed_tasks_count(self):
        return self.tasks.filter(status='COMPLETED').count()
    
    def get_total_tasks_count(self):
        return self.tasks.count()

    def _generate_join_code(self, length=8):
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(alphabet, k=length))
            if not self.__class__.objects.filter(join_code=code).exists():
                return code

    def save(self, *args, **kwargs):
        if not self.join_code:
            self.join_code = self._generate_join_code()
        while self.__class__.objects.filter(join_code=self.join_code).exclude(pk=self.pk).exists():
            self.join_code = self._generate_join_code()
        super().save(*args, **kwargs)

class Task(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('OVERDUE', 'Overdue'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='tasks')
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assigned_tasks')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    deadline = models.DateTimeField()
    file_link = models.URLField(blank=True, help_text="Google Drive or other file link")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['deadline', '-created_at']
    
    def __str__(self):
        return self.title
    
    def get_absolute_url(self):
        return reverse('task_detail', args=[self.id])
    
    def is_overdue(self):
        if self.status != 'COMPLETED' and self.deadline < timezone.now():
            return True
        return False
    
    def mark_completed(self):
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()
    
    def save(self, *args, **kwargs):
        if not self.status == 'COMPLETED' and self.deadline < timezone.now():
            self.status = 'OVERDUE'
        super().save(*args, **kwargs)

class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ('TASK_CREATED', 'Task Created'),
        ('TASK_UPDATED', 'Task Updated'),
        ('TASK_DELETED', 'Task Deleted'),
        ('TASK_COMPLETED', 'Task Completed'),
        ('GROUP_CREATED', 'Group Created'),
        ('GROUP_DELETED', 'Group Deleted'),
        ('GROUP_JOINED', 'Group Joined'),
        ('MEMBER_REMOVED', 'Member Removed'),
        ('TASK_ASSIGNED', 'Task Assigned'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True, related_name='activities')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True, related_name='activities')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.timestamp}"
