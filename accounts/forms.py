from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class StyledUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget = forms.TextInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Choose a username',
                'autocomplete': 'username',
            }
        )
        self.fields['password1'].widget = forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Create a password',
                'autocomplete': 'new-password',
            }
        )
        self.fields['password2'].widget = forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Confirm your password',
                'autocomplete': 'new-password',
            }
        )


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields['username'].widget = forms.TextInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Username',
                'autocomplete': 'username',
            }
        )
        self.fields['password'].widget = forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Password',
                'autocomplete': 'current-password',
            }
        )
