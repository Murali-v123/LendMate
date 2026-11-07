from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User

from core.forms import BootstrapFormMixin


class RegistrationForm(BootstrapFormMixin, UserCreationForm):
    full_name = forms.CharField(max_length=150, label="Full name")
    email = forms.EmailField(label="Email address", help_text="Used for password resets.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    field_order = ["full_name", "username", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["full_name"].strip()[:150]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LendMateAuthenticationForm(BootstrapFormMixin, AuthenticationForm):
    pass


class LendMatePasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass
