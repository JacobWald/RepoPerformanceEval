from django import forms

class SupaSignupForm(forms.Form):
    username = forms.CharField(
        required=True, max_length=30,
        widget=forms.TextInput(attrs={"placeholder": "yourname", "class": "form-control"})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "class": "form-control"})
    )
    password1 = forms.CharField(
        required=True, min_length=6,
        widget=forms.PasswordInput(attrs={"placeholder": "Password (min 6 chars)", "class": "form-control"})
    )
    password2 = forms.CharField(
        required=True, min_length=6,
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm password", "class": "form-control"})
    )

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned


class SupaLoginForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "class": "form-control"})
    )
    password = forms.CharField(
        required=True, min_length=6,
        widget=forms.PasswordInput(attrs={"placeholder": "Password", "class": "form-control"})
    )
