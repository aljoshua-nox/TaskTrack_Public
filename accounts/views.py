from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import StyledAuthenticationForm, StyledUserCreationForm


def _safe_next_url(request):
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    # Only same-site paths are allowed, so ?next= can't be used to bounce users to another site.
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ''

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
    next_url = _safe_next_url(request)
    if request.method == 'POST':
        form = StyledAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            return redirect(next_url or 'core:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = StyledAuthenticationForm(request)
    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})

def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('accounts:login')
