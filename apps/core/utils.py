import re

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_to_en = str.maketrans(FA_DIGITS + AR_DIGITS, "0123456789" * 2)
_to_fa = str.maketrans("0123456789", FA_DIGITS)


def en_digits(value):
    """تبدیل ارقام فارسی/عربی به انگلیسی (برای ورودی کاربر)."""
    return str(value or "").translate(_to_en)


def fa_digits(value):
    return str(value).translate(_to_fa)


def normalize_phone(value):
    """۰۹۱۲... / +98912... / 912... → 09xxxxxxxxx یا None."""
    v = re.sub(r"[\s\-()]", "", en_digits(value))
    if v.startswith("+98"):
        v = "0" + v[3:]
    elif v.startswith("0098"):
        v = "0" + v[4:]
    elif v.startswith("9") and len(v) == 10:
        v = "0" + v
    return v if re.fullmatch(r"09\d{9}", v) else None


def format_toman(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    return fa_digits(f"{n:,}").replace(",", "٬")


def parse_int(value, default=None):
    try:
        return int(en_digits(value).replace(",", "").replace("٬", ""))
    except (TypeError, ValueError):
        return default
