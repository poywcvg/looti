import re

from django import forms

from apps.accounts.forms import parse_amount
from apps.core.utils import en_digits, fa_digits, normalize_phone

from .models import Listing, Offer, Report

MAX_IMAGES = 6
MAX_IMAGE_MB = 4


class ListingForm(forms.ModelForm):
    price = forms.CharField(label="قیمت (تومان)")
    platforms = forms.MultipleChoiceField(label="پلتفرم‌ها", required=True)
    # تا ۳ راه ارتباطی — هر ردیف: پیام‌رسان + آیدی. خالی یعنی «ندارم».
    MAX_CONTACTS = 3
    contact_app_0 = forms.ChoiceField(label="پیام‌رسان ۱", required=False)
    contact_id_0 = forms.CharField(label="آیدی / شماره ۱", max_length=64, required=False)
    contact_app_1 = forms.ChoiceField(label="پیام‌رسان ۲", required=False)
    contact_id_1 = forms.CharField(label="آیدی / شماره ۲", max_length=64, required=False)
    contact_app_2 = forms.ChoiceField(label="پیام‌رسان ۳", required=False)
    contact_id_2 = forms.CharField(label="آیدی / شماره ۳", max_length=64, required=False)

    class Meta:
        model = Listing
        fields = [
            "title", "description", "price", "negotiable", "open_to_trade", "trade_with", "platforms", "region", "level",
            "email_access", "first_owner", "ban_free", "has_2fa", "fee_payer",
        ]

    def __init__(self, *args, game, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Listing as _Listing
        self.game = game
        self.fields["platforms"].choices = game.platform_choices
        # گزینه‌های پیام‌رسان برای هر ۳ ردیف
        contact_choices = [("", "انتخاب کنید")] + list(_Listing.ContactApp.choices)
        for i in range(self.MAX_CONTACTS):
            self.fields[f"contact_app_{i}"].choices = contact_choices
        # مقدار اولیه پلتفرم‌ها: ویرایش → مقادیر ذخیره‌شده؛ جدید → همه پلتفرم‌های بازی اگر تکی است
        if self.instance.pk:
            initial_platforms = self.instance.platform_list or ([self.instance.platform] if getattr(self.instance, "platform", "") else [])
            if initial_platforms:
                self.initial["platforms"] = initial_platforms
            contacts = self.instance.contacts_list
            for i in range(self.MAX_CONTACTS):
                if i < len(contacts):
                    self.initial[f"contact_app_{i}"] = contacts[i]["app"]
                    self.initial[f"contact_id_{i}"] = contacts[i]["id"]
        else:
            # پیش‌فرض: اگر بازی فقط یک پلتفرم دارد همان تیک بخورد
            if len(game.platforms) == 1:
                self.initial["platforms"] = list(game.platforms)
        self.attr_fields = []
        current = (self.instance.attrs or {}) if self.instance.pk else {}
        for spec in game.attribute_schema:
            name = f"attr_{spec['key']}"
            kind = spec.get("type", "text")
            if kind == "number":
                field = forms.IntegerField(min_value=0, required=False)
            elif kind == "select":
                field = forms.ChoiceField(choices=[("", "انتخاب کنید")] + [(o, o) for o in spec.get("options", [])], required=False)
            elif kind == "bool":
                field = forms.BooleanField(required=False)
            else:
                field = forms.CharField(max_length=80, required=False)
            field.label = spec["label"]
            field.spec = spec
            if spec["key"] in current:
                field.initial = current[spec["key"]]
            self.fields[name] = field
            self.attr_fields.append(name)
        if self.instance.pk:
            self.initial["price"] = self.instance.price

    def bound_attr_fields(self):
        return [self[n] for n in self.attr_fields]

    def clean_price(self):
        value = parse_amount(self.cleaned_data["price"])
        if not value or value < 50_000:
            raise forms.ValidationError("قیمت باید حداقل ۵۰٬۰۰۰ تومان باشد.")
        if value > 5_000_000_000:
            raise forms.ValidationError("قیمت واردشده غیرعادی است.")
        return value

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 8:
            raise forms.ValidationError("عنوان را کمی کامل‌تر بنویسید (حداقل ۸ حرف).")
        return title

    def clean_trade_with(self):
        return (self.cleaned_data.get("trade_with") or "").strip()

    def clean_platforms(self):
        values = self.cleaned_data.get("platforms") or []
        # request.POST.getlist در بایندینگ چندتایی می‌آید؛ اگر تک‌رشته آمد لیستش کن
        if isinstance(values, str):
            values = [values]
        allowed = {k for k, _ in self.game.platform_choices}
        values = [v for v in values if v in allowed]
        if not values:
            raise forms.ValidationError("حداقل یک پلتفرم انتخاب کنید.")
        # ترتیب گزینه‌های بازی حفظ شود تا «اصلی» قابل پیش‌بینی باشد
        order = [k for k, _ in self.game.platform_choices]
        values.sort(key=lambda v: order.index(v) if v in order else 99)
        return values

    def clean(self):
        data = super().clean()
        # اگر تیک معاوضه خاموش است، توضیح معاوضه ذخیره نشود
        if not data.get("open_to_trade"):
            data["trade_with"] = self.instance.trade_with = ""
        # --- پلتفرم چندتایی: همگام‌سازی فیلد تکی قدیمی (اصلی = اولی) ---
        platforms = data.get("platforms") or []
        if platforms:
            self.instance.platforms = platforms
            self.instance.platform = platforms[0]
            data["platforms"] = platforms
        elif self.instance.pk and not self.errors.get("platforms"):
            # ویرایش بدون تغییر؟ مقدار قبلی بماند
            pass
        # --- راه‌های ارتباطی چندتایی (حداکثر ۳، تکراری ممنوع) ---
        contacts = []
        seen_apps = set()
        for i in range(self.MAX_CONTACTS):
            app = (data.get(f"contact_app_{i}") or "").strip()
            raw = (data.get(f"contact_id_{i}") or "").strip()
            if not app and not raw:
                continue
            if app and not raw:
                self.add_error(f"contact_id_{i}", "آیدی یا شماره را بنویس.")
                continue
            if raw and not app:
                self.add_error(f"contact_app_{i}", "پیام‌رسان را انتخاب کن.")
                continue
            if app in seen_apps:
                self.add_error(f"contact_app_{i}", "این پیام‌رسان را قبلاً اضافه کرده‌ای.")
                continue
            value, error = clean_contact(app, raw)
            if error:
                self.add_error(f"contact_id_{i}", error)
                continue
            seen_apps.add(app)
            contacts.append({"app": app, "id": value})
        self.instance.contacts = contacts
        # سازگاری: فیلدهای تکی = راه اول
        if contacts:
            self.instance.contact_app = contacts[0]["app"]
            self.instance.contact_id = contacts[0]["id"]
        else:
            self.instance.contact_app = ""
            self.instance.contact_id = ""
        attrs = {}
        for n in self.attr_fields:
            val = data.get(n)
            if val not in (None, "", False):
                attrs[self.fields[n].spec["key"]] = val
        self.instance.attrs = attrs
        self.instance.game = self.game
        return data


CONTACT_HOSTS = ("t.me/", "telegram.me/", "wa.me/", "instagram.com/", "eitaa.com/", "ble.ir/", "rubika.ir/")


def clean_contact(app, raw):
    """آیدی پیام‌رسان را یکدست می‌کند: @ و لینک کامل را برمی‌دارد و قالب را بررسی می‌کند."""
    value = en_digits(raw).strip()
    for prefix in ("https://", "http://", "www."):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    for host in CONTACT_HOSTS:
        if value.lower().startswith(host):
            value = value[len(host):]
    value = value.strip("/").lstrip("@").strip()
    if app == "whatsapp":
        digits = re.sub(r"[\s\-()+]", "", value)
        phone = normalize_phone(digits)
        if phone:
            return "98" + phone[1:], None
        if re.fullmatch(r"\d{10,15}", digits) and not digits.startswith("0"):
            return digits, None
        return None, "شماره واتس‌اپ معتبر نیست؛ مثل ۰۹۱۲۱۲۳۴۵۶۷"
    if app == "discord":
        if re.fullmatch(r"[a-z0-9_.]{2,32}", value.lower()):
            return value.lower(), None
        return None, "نام کاربری دیسکورد ۲ تا ۳۲ حرف انگلیسی کوچک، عدد، نقطه یا _ است."
    if app == "instagram":
        if re.fullmatch(r"[A-Za-z0-9_.]{1,30}", value):
            return value, None
        return None, "آیدی اینستاگرام فقط حرف انگلیسی، عدد، نقطه و _ دارد."
    min_len = 5 if app == "telegram" else 3
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{%d,31}" % (min_len - 1), value):
        return value, None
    return None, f"آیدی معتبر نیست؛ با حرف انگلیسی شروع شود و حداقل {fa_digits(min_len)} نویسه باشد (مثل @looti_shop)."


def clean_images(files):
    if len(files) > MAX_IMAGES:
        raise forms.ValidationError(f"حداکثر {MAX_IMAGES} تصویر می‌توانید بارگذاری کنید.")
    for f in files:
        if f.size > MAX_IMAGE_MB * 1024 * 1024:
            raise forms.ValidationError(f"حجم هر تصویر حداکثر {MAX_IMAGE_MB} مگابایت باشد.")
        if (f.content_type or "").split("/")[0] != "image":
            raise forms.ValidationError("فقط فایل تصویری مجاز است.")
        forms.ImageField().clean(f)
    return files


class OfferForm(forms.ModelForm):
    amount = forms.CharField()

    class Meta:
        model = Offer
        fields = ["amount"]

    def __init__(self, *args, listing, **kwargs):
        super().__init__(*args, **kwargs)
        self.listing = listing

    def clean_amount(self):
        value = parse_amount(self.cleaned_data["amount"])
        if not value:
            raise forms.ValidationError("مبلغ پیشنهادی را وارد کنید.")
        if value < self.listing.price * 0.5:
            raise forms.ValidationError("پیشنهاد کمتر از نصف قیمت پذیرفته نمی‌شود.")
        if value >= self.listing.price:
            raise forms.ValidationError("پیشنهاد باید کمتر از قیمت آگهی باشد؛ برای قیمت کامل مستقیم خرید کنید.")
        return value


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason", "text"]
