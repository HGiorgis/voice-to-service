from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

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

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        cfg = AntiAbuseSettings.get_settings()
        if not cfg.master_enable:
            return email
        dom = email_domain(email)
        if cfg.block_disposable_email and dom and is_disposable_domain(dom):
            raise ValidationError(
                'Temporary or disposable email addresses are not allowed. '
                'Use Gmail or sign in with Google.'
            )
        if cfg.require_gmail_domain_for_password_signup and dom and not is_gmail_domain(dom):
            raise ValidationError(
                'Password sign-up requires a Gmail address (@gmail.com), or use Google sign-in.'
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