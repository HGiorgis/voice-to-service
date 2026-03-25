from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.authentication.antiabuse import (
    PUBLIC_DISPOSABLE_EMAIL_DENIED_MESSAGE,
    PUBLIC_GMAIL_ONLY_SIGNUP_MESSAGE,
)
from apps.authentication.disposable_email import email_domain, is_disposable_domain, is_gmail_domain
from apps.authentication.models import AntiAbuseSettings

User = get_user_model()

class CustomUserCreationForm(UserCreationForm):
    """Custom registration form"""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter your email'})
    )
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose a username'})
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Create a password'})
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm your password'})
    )
    company_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your company name (optional)'})
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number (optional)'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2', 'company_name', 'phone')

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise ValidationError('Enter a username.')
        lookup = User.normalize_username(username)
        if User.objects.filter(username__iexact=lookup).exists():
            raise ValidationError('That username is already taken. Try a different one.')
        return lookup

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise ValidationError('Enter your email address.')
        cfg = AntiAbuseSettings.get_settings()
        if cfg.master_enable:
            dom = email_domain(email)
            if cfg.block_disposable_email and dom and is_disposable_domain(dom):
                raise ValidationError(PUBLIC_DISPOSABLE_EMAIL_DENIED_MESSAGE)
            if cfg.require_gmail_domain_for_password_signup and dom and not is_gmail_domain(dom):
                raise ValidationError(PUBLIC_GMAIL_ONLY_SIGNUP_MESSAGE)
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                'That email is already registered. Sign in or use a different address.'
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.company_name = self.cleaned_data.get('company_name', '')
        user.phone = self.cleaned_data.get('phone', '')
        if commit:
            user.save()
        return user


def registration_invalid_toast_message(form: CustomUserCreationForm) -> str:
    """One clear toast line from form errors (field help remains under each input)."""
    if not form.errors:
        return 'Unable to register. Please check your details and try again.'
    order = ('email', 'username', 'password2', 'password1', '__all__')
    parts: list[str] = []
    for name in order:
        if name not in form.errors:
            continue
        for e in form.errors[name]:
            parts.append(str(e))
    for name in form.errors:
        if name in order:
            continue
        for e in form.errors[name]:
            parts.append(str(e))
    return '; '.join(parts) if parts else 'Unable to register. Please check your details and try again.'


class PendingSignupChangeEmailForm(forms.Form):
    """Correct email before OTP during pending verification."""

    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={'class': 'form-control', 'placeholder': 'Correct email address', 'autocomplete': 'email'}
        ),
    )

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise ValidationError('Enter your email address.')
        if not self.current_user:
            return email
        cfg = AntiAbuseSettings.get_settings()
        if cfg.master_enable:
            dom = email_domain(email)
            if cfg.block_disposable_email and dom and is_disposable_domain(dom):
                raise ValidationError(PUBLIC_DISPOSABLE_EMAIL_DENIED_MESSAGE)
            if cfg.require_gmail_domain_for_password_signup and dom and not is_gmail_domain(dom):
                raise ValidationError(PUBLIC_GMAIL_ONLY_SIGNUP_MESSAGE)
        taken = User.objects.filter(email__iexact=email).exclude(pk=self.current_user.pk).exists()
        if taken:
            raise ValidationError(
                'That email is already in use. Choose a different address or sign in.'
            )
        return email


class PendingSignupChangeUsernameForm(forms.Form):
    """One-time username fix on the verify page."""

    username = forms.CharField(
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Username', 'autocomplete': 'username'}
        ),
    )

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise ValidationError('Enter a username.')
        lookup = User.normalize_username(username)
        qs = User.objects.filter(username__iexact=lookup)
        if self.current_user:
            qs = qs.exclude(pk=self.current_user.pk)
        if qs.exists():
            raise ValidationError('That username is already taken. Try a different one.')
        return lookup


class VerifyEmailForm(forms.Form):
    """Complete password signup after OTP is sent."""

    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'First name', 'autocomplete': 'given-name'}
        ),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Last name', 'autocomplete': 'family-name'}
        ),
    )
    code = forms.CharField(
        min_length=6,
        max_length=8,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control text-center',
                'placeholder': '6-digit code',
                'autocomplete': 'one-time-code',
                'inputmode': 'numeric',
                'pattern': '[0-9]*',
                'style': 'letter-spacing:0.25em;font-size:1.25rem;',
            }
        ),
    )

    def clean_code(self):
        c = (self.cleaned_data.get('code') or '').strip().replace(' ', '')
        if not c.isdigit():
            raise forms.ValidationError('Enter the numeric code from your email.')
        if len(c) != 6:
            raise forms.ValidationError('The code must be 6 digits.')
        return c


class CustomAuthenticationForm(AuthenticationForm):
    """Custom login form"""
    
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter your username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter your password'})
    )
    
    class Meta:
        model = User


class UserProfileForm(forms.ModelForm):
    """Profile update form"""
    
    class Meta:
        model = User
        fields = ('email', 'company_name', 'phone')
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ChangePasswordForm(forms.Form):
    """Change password form"""
    
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        return cleaned_data