from django.contrib.auth.backends import ModelBackend

from apps.core.utils import en_digits, normalize_phone

from .models import User


def find_user(identifier):
    """شماره موبایل، نام کاربری یا ایمیل → کاربر یا None."""
    ident = en_digits(identifier or "").strip()
    if not ident:
        return None
    phone = normalize_phone(ident)
    if phone:
        lookup = {"phone": phone}
    elif "@" in ident:
        lookup = {"email": ident.lower()}
    else:
        lookup = {"username": ident.lower()}
    return User.objects.filter(**lookup).first()


class IdentifierBackend(ModelBackend):
    """ورود با رمز عبور و یکی از شناسه‌ها: موبایل، نام کاربری یا ایمیل."""

    def authenticate(self, request, identifier=None, password=None, **kwargs):
        identifier = identifier if identifier is not None else kwargs.get("username")  # فرم ورود ادمین جنگو username می‌فرستد
        if identifier is None or password is None:
            return None
        user = find_user(identifier)
        if user is None:
            # هش‌کردن بی‌نتیجه تا زمان پاسخ، وجود یا نبود حساب را لو ندهد
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
