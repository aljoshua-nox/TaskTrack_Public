from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages

from .forms import StyledAuthenticationForm, StyledUserCreationForm

def register_view(request):
    if request.method == 'POST':
        form = StyledUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful! Welcome to TaskTrack!')
            return redirect('core:dashboard')
        else:
            messages.error(request, 'Registration failed. Please correct the errors below.')
    else:
        form = StyledUserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = StyledAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            return redirect('core:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = StyledAuthenticationForm(request)
    return render(request, 'accounts/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('accounts:login')
