from django.contrib.auth.password_validation import MinimumLengthValidator
from django.core.exceptions import ValidationError

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class PersianMinimumLengthValidator(MinimumLengthValidator):
    """همان اعتبارسنج طول رمز جنگو؛ ترجمه‌ی فارسی خودش برای این پیام جمع‌دار خالی است و متن انگلیسی نشان می‌داد."""

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(f"رمز خیلی کوتاه است؛ دست‌کم {str(self.min_length).translate(FA_DIGITS)} نویسه لازم است.", code="password_too_short",
                                  params={"min_length": self.min_length})

    def get_help_text(self):
        return f"رمز باید دست‌کم {str(self.min_length).translate(FA_DIGITS)} نویسه باشد."
