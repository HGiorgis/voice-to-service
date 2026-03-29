from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.authentication.antiabuse import (
    PUBLIC_DISPOSABLE_EMAIL_DENIED_MESSAGE,
    PUBLIC_GMAIL_ONLY_SIGNUP_MESSAGE,
)
from apps.authentication.disposable_email import email_domain, is_disposable_domain, is_gmail_domain
from apps.authentication.models import AntiAbuseSettings
from apps.users.username_utils import allocate_username_from_email

User = get_user_model()

class CustomUserCreationForm(UserCreationForm):
    """Custom registration form"""
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter your email'})
    )
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Optional — we’ll pick one from your email if empty',
            }
        ),
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
        fields = ('email', 'username', 'password1', 'password2', 'company_name', 'phone')

    def clean(self):
        email = (self.cleaned_data.get('email') or '').strip()
        un = (self.cleaned_data.get('username') or '').strip()
        if email and not un:
            self.cleaned_data['username'] = allocate_username_from_email(email)
        cleaned = super().clean()
        email = (cleaned.get('email') or '').strip()
        if not email:
            return cleaned
        existing = User.objects.filter(email__iexact=email).first()
        if not existing:
            return cleaned
        if existing.is_verified:
            self.add_error(
                'email',
                'That email is already registered. Sign in or use a different address.',
            )
            return cleaned
        pw1 = cleaned.get('password1') or ''
        pw2 = cleaned.get('password2') or ''
        if (
            pw1
            and pw2
            and pw1 == pw2
            and existing.has_usable_password()
            and existing.check_password(pw1)
        ):
            return cleaned
        if pw1 and pw2 and pw1 == pw2:
            self.add_error(
                'email',
                'That email is already registered. Sign in or use a different address.',
            )
        return cleaned

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            return ''
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


class VerifyEmailForm(forms.Form):
    """Complete password signup after OTP is sent."""

    code = forms.CharField(
        label='Verification code',
        min_length=6,
        max_length=8,
        widget=forms.HiddenInput(attrs={'id': 'id_code', 'autocomplete': 'one-time-code'}),
    )
    first_name = forms.CharField(
        label='First name',
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'First name', 'autocomplete': 'given-name'}
        ),
    )
    last_name = forms.CharField(
        label='Last name',
        max_length=150,
        required=True,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Last name', 'autocomplete': 'family-name'}
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
        label='Email or username',
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Email or username'}
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter your password'})
    )

    def clean(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if username and '@' in username:
            match = User.objects.filter(email__iexact=username).first()
            if match:
                self.cleaned_data['username'] = match.username
        return super().clean()

    class Meta:
        model = User


class UserProfileForm(forms.ModelForm):
    """Profile update (email is not editable here)."""

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'company_name', 'phone')
        widgets = {
            'first_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'First name', 'autocomplete': 'given-name'}
            ),
            'last_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'Last name', 'autocomplete': 'family-name'}
            ),
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company (optional)'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone (optional)'}),
        }


class ChangePasswordForm(forms.Form):
    """Change password: Google-only users may leave current password empty."""

    current_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'current-password'}
        ),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}
        ),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user and user.has_usable_password():
            self.fields['current_password'].required = True
            self.fields['current_password'].widget.attrs.setdefault(
                'placeholder', 'Current password'
            )
        else:
            self.fields['current_password'].widget.attrs.setdefault(
                'placeholder', 'Leave blank if you use Google sign-in'
            )

    def clean_new_password(self):
        pwd = self.cleaned_data.get('new_password')
        if pwd and self.user:
            validate_password(pwd, self.user)
        return pwd

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error('confirm_password', 'The two new passwords do not match.')

        u = self.user
        if u and u.has_usable_password():
            cur = (cleaned_data.get('current_password') or '').strip()
            if not cur:
                self.add_error('current_password', 'Enter your current password.')
            elif not u.check_password(cur):
                self.add_error('current_password', 'Current password is incorrect.')

        return cleaned_data