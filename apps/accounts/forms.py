import re

from django import forms
from django.contrib.auth import password_validation

from apps.core.utils import en_digits, fa_digits, format_toman, normalize_phone

from .models import User


class PhoneForm(forms.Form):
    phone = forms.CharField(label="شماره موبایل", max_length=20)

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("شماره موبایل معتبر نیست؛ مثل ۰۹۱۲۱۲۳۴۵۶۷")
        return phone


class PasswordLoginForm(forms.Form):
    identifier = forms.CharField(label="موبایل، نام کاربری یا ایمیل", max_length=254)
    password = forms.CharField(label="رمز عبور", max_length=128, strip=False)


USERNAME_RE = re.compile(r"[a-z][a-z0-9_.]{2,29}")
RESERVED_USERNAMES = {"admin", "looti", "gamanat", "support", "panel", "root", "staff", "mediator"}


def check_username(name, exclude_pk=None):
    if not USERNAME_RE.fullmatch(name):
        raise forms.ValidationError("۳ تا ۳۰ حرف انگلیسی کوچک، عدد، نقطه یا _ ؛ با حرف شروع شود.")
    if name in RESERVED_USERNAMES:
        raise forms.ValidationError("این نام کاربری رزرو شده است.")
    if User.objects.filter(username=name).exclude(pk=exclude_pk).exists():
        raise forms.ValidationError("این نام کاربری قبلاً گرفته شده.")
    return name


class RegisterForm(forms.Form):
    """ثبت‌نام: نام نمایشی، نام کاربری، موبایل و رمز. تا تأیید کد پیامکی فقط هش رمز در نشست می‌ماند."""

    display_name = forms.CharField(label="نام نمایشی", max_length=40)
    username = forms.CharField(label="نام کاربری", max_length=30)
    phone = forms.CharField(label="شماره موبایل", max_length=20)
    password = forms.CharField(label="رمز عبور", max_length=128, strip=False)

    def clean_display_name(self):
        name = " ".join(self.cleaned_data["display_name"].split())
        if len(name) < 3:
            raise forms.ValidationError("نام نمایشی دست‌کم ۳ حرف باشد.")
        return name

    def clean_username(self):
        return check_username(en_digits(self.cleaned_data["username"]).strip().lower().lstrip("@"))

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("شماره موبایل معتبر نیست؛ مثل ۰۹۱۲۱۲۳۴۵۶۷")
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError("این شماره قبلاً حساب دارد؛ از «ورود» وارد شو.")
        return phone

    def clean(self):
        data = super().clean()
        pw = data.get("password")
        if pw:
            probe = User(phone=data.get("phone") or "", username=data.get("username") or "", display_name=data.get("display_name") or "")
            try:
                password_validation.validate_password(pw, probe)
            except forms.ValidationError as e:
                self.add_error("password", e)
        return data


class LoginIdentityForm(forms.ModelForm):
    """نام کاربری و ایمیل — هر دو اختیاری، برای ورود با رمز."""

    class Meta:
        model = User
        fields = ["username", "email"]

    def clean_username(self):
        name = en_digits(self.cleaned_data.get("username") or "").strip().lower()
        return check_username(name, exclude_pk=self.instance.pk) if name else None

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return None
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("این ایمیل به حساب دیگری وصل است.")
        return email


class SetPasswordForm(forms.Form):
    """تعیین یا تغییر رمز. رمز فعلی فقط وقتی لازم است که رمزی هست و کاربر تازه با پیامک وارد نشده."""

    current_password = forms.CharField(label="رمز فعلی", required=False, strip=False)
    new_password1 = forms.CharField(label="رمز تازه", strip=False)
    new_password2 = forms.CharField(label="تکرار رمز تازه", strip=False)

    def __init__(self, user, *args, require_current=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.require_current = user, require_current

    def clean_current_password(self):
        current = self.cleaned_data.get("current_password", "")
        if self.require_current and not self.user.check_password(current):
            raise forms.ValidationError("رمز فعلی درست نیست.")
        return current

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("new_password1"), data.get("new_password2")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password2", "دو رمز یکی نیستند.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as e:
                self.add_error("new_password1", e)
        return data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "bio", "avatar", "sheba"]

    def clean_display_name(self):
        name = self.cleaned_data["display_name"].strip()
        if len(name) < 3:
            raise forms.ValidationError("نام نمایشی حداقل ۳ حرف باشد.")
        return name

    def clean_sheba(self):
        sheba = en_digits(self.cleaned_data.get("sheba", "")).upper().replace(" ", "").replace("IR", "")
        if not sheba:
            return ""
        if not sheba.isdigit() or len(sheba) != 24:
            raise forms.ValidationError("شبا باید ۲۴ رقم بعد از IR باشد.")
        return "IR" + sheba


def parse_amount(raw):
    raw = en_digits(str(raw or "")).replace(",", "").replace("٬", "").strip()
    return int(raw) if raw.isdigit() else None


class AmountForm(forms.Form):
    amount = forms.CharField(label="مبلغ (تومان)")

    def __init__(self, *args, min_amount=10_000, max_amount=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.min_amount, self.max_amount = min_amount, max_amount

    def clean_amount(self):
        value = parse_amount(self.cleaned_data["amount"])
        if value is None:
            raise forms.ValidationError("مبلغ را به عدد وارد کنید.")
        if value < self.min_amount:
            raise forms.ValidationError(f"حداقل مبلغ {format_toman(self.min_amount)} تومان است.")
        if self.max_amount is not None and value > self.max_amount:
            raise forms.ValidationError("مبلغ بیشتر از سقف مجاز یا موجودی شماست.")
        return value


__all__ = ["PhoneForm", "PasswordLoginForm", "RegisterForm", "LoginIdentityForm", "SetPasswordForm", "ProfileForm", "AmountForm", "parse_amount", "fa_digits"]
