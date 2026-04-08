from django.utils import timezone
from django import forms
from django.contrib.auth.models import User
from .models import Group, Task


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Group Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Group Description'}),
        }

class TaskForm(forms.ModelForm):
    deadline = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'type': 'datetime-local', 'class': 'form-control'})
    )
    
    class Meta:
        model = Task
        fields = ['title', 'description', 'assigned_to', 'deadline', 'file_link']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Task Title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Task Description'}),
            'assigned_to': forms.Select(attrs={'class': 'form-control'}),
            'file_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://drive.google.com/...'}),
        }
    
    def __init__(self, *args, **kwargs):
        group = kwargs.pop('group', None)
        super().__init__(*args, **kwargs)
        if group:
            self.fields['assigned_to'].queryset = group.members.all()

    def clean_deadline(self):
        deadline = self.cleaned_data['deadline']
        if deadline < timezone.now():
            raise forms.ValidationError("Deadline cannot be in the past.")
        return deadline

class TaskUpdateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['status', 'file_link']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control'}),
            'file_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://drive.google.com/...'}),
        }

class JoinGroupForm(forms.Form):
    join_code = forms.CharField(
        max_length=8,
        min_length=8,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Enter 8-character group code'}
        ),
    )

    def clean_join_code(self):
        return self.cleaned_data['join_code'].strip().upper()
