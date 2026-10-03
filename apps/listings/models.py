import secrets
import statistics
from functools import lru_cache

from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.db import models
from django.urls import reverse
from django.utils import timezone

PLATFORM_CHOICES = [
    ("pc", "PC"),
    ("playstation", "پلی‌استیشن"),
    ("xbox", "ایکس‌باکس"),
    ("mobile", "موبایل"),
    ("switch", "نینتندو سوییچ"),
    ("cross", "کراس‌پلتفرم"),
]
PLATFORM_ICONS = {
    "pc": "monitor",
    "playstation": "gamepad-2",
    "xbox": "gamepad",
    "mobile": "smartphone",
    "switch": "joystick",
    "cross": "layers",
}


@lru_cache(maxsize=64)
def _game_cover(slug):
    rel = f"img/games/{slug}.webp"
    return static(rel) if finders.find(rel) else ""


class Game(models.Model):
    name = models.CharField("نام", max_length=60)
    name_en = models.CharField("نام لاتین", max_length=60)
    slug = models.SlugField(unique=True)
    icon = models.CharField("آیکن Lucide", max_length=40, default="gamepad-2")
    tone = models.CharField("رنگ کارت", max_length=7, default="#C8553D")
    tagline = models.CharField("توضیح کوتاه", max_length=120, blank=True)
    platforms = models.JSONField("پلتفرم‌ها", default=list)
    attribute_schema = models.JSONField(
        "فیلدهای اختصاصی",
        default=list,
        help_text='لیستی از {"key","label","type":number|select|text|bool,"options":[],"unit":"","icon":""}',
    )
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "بازی"
        verbose_name_plural = "بازی‌ها"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("listings:list") + f"?game={self.slug}"

    @property
    def cover_url(self):
        """کاور رسمی بازی در static/img/games/<slug>.webp؛ اگر نبود رشته خالی."""
        return _game_cover(self.slug)

    @property
    def platform_choices(self):
        return [(k, v) for k, v in PLATFORM_CHOICES if k in self.platforms] or PLATFORM_CHOICES

    def median_price(self, exclude_pk=None):
        prices = list(
            self.listings.filter(status__in=[Listing.Status.ACTIVE, Listing.Status.SOLD, Listing.Status.RESERVED])
            .exclude(pk=exclude_pk)
            .values_list("price", flat=True)[:200]
        )
        return statistics.median(prices) if len(prices) >= 3 else None


def _code():
    return "G" + secrets.token_hex(3).upper()


class ListingQuerySet(models.QuerySet):
    def public(self):
        return self.filter(status=Listing.Status.ACTIVE).select_related("game", "seller").prefetch_related("images")


class Listing(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تأیید"
        ACTIVE = "active", "فعال"
        RESERVED = "reserved", "در حال معامله"
        SOLD = "sold", "فروخته شد"
        REJECTED = "rejected", "رد شده"
        ARCHIVED = "archived", "بسته‌شده"

    class EmailAccess(models.TextChoices):
        FULL = "full", "ایمیل اصلی تحویل داده می‌شود"
        CHANGEABLE = "changeable", "ایمیل قابل تغییر است"
        NONE = "none", "دسترسی ایمیل ندارد"

    class ContactApp(models.TextChoices):
        TELEGRAM = "telegram", "تلگرام"
        WHATSAPP = "whatsapp", "واتس‌اپ"
        INSTAGRAM = "instagram", "اینستاگرام"
        DISCORD = "discord", "دیسکورد"
        EITAA = "eitaa", "ایتا"
        BALE = "bale", "بله"
        RUBIKA = "rubika", "روبیکا"

    class FeePayer(models.TextChoices):
        BUYER = "buyer", "خریدار"
        SELLER = "seller", "فروشنده"
        SPLIT = "split", "نصف‌نصف"

    code = models.CharField(max_length=8, unique=True, default=_code, editable=False)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    game = models.ForeignKey(Game, on_delete=models.PROTECT, related_name="listings")
    title = models.CharField("عنوان آگهی", max_length=80)
    description = models.TextField("توضیحات", max_length=3000)
    price = models.PositiveBigIntegerField("قیمت (تومان)")
    negotiable = models.BooleanField("قیمت توافقی است", default=False)
    open_to_trade = models.BooleanField("مایل به معاوضه هستم", default=False)
    trade_with = models.CharField("با چی معاوضه می‌کنم؟", max_length=200, blank=True)
    platform = models.CharField("پلتفرم", max_length=20, choices=PLATFORM_CHOICES)
    # چندپلتفرمی — پلتفرم‌های انتخاب‌شده؛ `platform` پلتفرم اصلی (اولی) است و برای سازگاری نگه داشته شده
    platforms = models.JSONField("پلتفرم‌ها (آگهی)", default=list, blank=True)
    region = models.CharField("ریجن / سرور", max_length=40, blank=True)
    level = models.PositiveIntegerField("لول / رنک عددی", null=True, blank=True)
    attrs = models.JSONField(default=dict, blank=True)
    email_access = models.CharField("وضعیت ایمیل", max_length=12, choices=EmailAccess.choices, default=EmailAccess.CHANGEABLE)
    first_owner = models.BooleanField("مالک اول هستم", default=False)
    ban_free = models.BooleanField("سابقه بن ندارد", default=True)
    has_2fa = models.BooleanField("تأیید دومرحله‌ای قابل انتقال", default=False)
    # راه ارتباط مستقیم (اختیاری) — فقط به کاربران واردشده و بعد از هشدار امنیتی نمایش داده می‌شود
    # `contact_app/contact_id` راه اول است (سازگاری)؛ `contacts` همه راه‌ها: [{"app":..., "id":...}]
    contact_app = models.CharField("پیام‌رسان", max_length=10, choices=ContactApp.choices, blank=True)
    contact_id = models.CharField("آیدی / شماره", max_length=64, blank=True)
    contacts = models.JSONField("راه‌های ارتباطی", default=list, blank=True)
    fee_payer = models.CharField("پرداخت کارمزد", max_length=8, choices=FeePayer.choices, default=FeePayer.BUYER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reject_reason = models.CharField(max_length=200, blank=True)
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    bumped_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        ordering = ["-bumped_at"]
        verbose_name = "آگهی"
        verbose_name_plural = "آگهی‌ها"

    def __str__(self):
        return f"{self.title} ({self.code})"

    def get_absolute_url(self):
        return reverse("listings:detail", args=[self.code])

    CONTACT_LINKS = {
        "telegram": "https://t.me/{}",
        "whatsapp": "https://wa.me/{}",
        "instagram": "https://instagram.com/{}",
        "eitaa": "https://eitaa.com/{}",
        "bale": "https://ble.ir/{}",
        "rubika": "https://rubika.ir/{}",
    }
    CONTACT_ICONS = {
        "telegram": "send", "whatsapp": "phone", "instagram": "at-sign", "discord": "headphones",
        "eitaa": "message-circle", "bale": "message-circle", "rubika": "message-circle",
    }
    CONTACT_APPS = dict(ContactApp.choices)
    PLATFORM_LABELS = dict(PLATFORM_CHOICES)

    # --- پلتفرم چندتایی -------------------------------------------------
    @property
    def platform_list(self):
        """کدهای پلتفرم: اگر `platforms` پر باشد همان، وگرنه `platform` تکی قدیمی."""
        if self.platforms:
            return [p for p in self.platforms if p in self.PLATFORM_LABELS]
        return [self.platform] if self.platform in self.PLATFORM_LABELS else []

    @property
    def platform_labels(self):
        """[(code, label, icon)] برای نمایش چیپ‌ها."""
        return [(c, self.PLATFORM_LABELS.get(c, c), PLATFORM_ICONS.get(c, "gamepad-2")) for c in self.platform_list]

    @property
    def platform_display_multi(self):
        return "، ".join(label for _, label, _ in self.platform_labels) or self.get_platform_display()

    # --- راه ارتباطی چندتایی ---------------------------------------------
    @property
    def contacts_list(self):
        """[{'app':..., 'id':...}] — اگر `contacts` پر باشد همان، وگرنه تک‌فیلد قدیمی."""
        if self.contacts:
            out = []
            for c in self.contacts:
                if isinstance(c, dict) and c.get("app") in self.CONTACT_APPS and c.get("id"):
                    out.append({"app": c["app"], "id": c["id"]})
            if out:
                return out
        if self.contact_app and self.contact_id:
            return [{"app": self.contact_app, "id": self.contact_id}]
        return []

    @staticmethod
    def _contact_display(app, cid):
        if app == "whatsapp":
            return "+" + cid
        if app == "discord":
            return cid
        return "@" + cid

    @staticmethod
    def _contact_url(app, cid):
        tpl = Listing.CONTACT_LINKS.get(app)
        return tpl.format(cid) if tpl and cid else ""

    @property
    def contacts_enriched(self):
        """[{'app','id','label','display','url','icon'}] برای قالب‌ها."""
        rows = []
        for c in self.contacts_list:
            app, cid = c["app"], c["id"]
            rows.append({
                "app": app, "id": cid,
                "label": self.CONTACT_APPS.get(app, app),
                "display": self._contact_display(app, cid),
                "url": self._contact_url(app, cid),
                "icon": self.CONTACT_ICONS.get(app, "message-circle"),
            })
        return rows

    @property
    def has_contact(self):
        return bool(self.contacts_list)

    @property
    def contact_url(self):
        """لینک مستقیم پیام‌رسان اول؛ دیسکورد لینک عمومی ندارد."""
        first = self.contacts_list[:1]
        if not first:
            return ""
        return self._contact_url(first[0]["app"], first[0]["id"])

    @property
    def contact_display(self):
        first = self.contacts_list[:1]
        if not first:
            return ""
        return self._contact_display(first[0]["app"], first[0]["id"])

    @property
    def contact_icon(self):
        first = self.contacts_list[:1]
        if not first:
            return "message-circle"
        return self.CONTACT_ICONS.get(first[0]["app"], "message-circle")

    @property
    def cover(self):
        imgs = list(self.images.all())
        return imgs[0] if imgs else None

    @property
    def platform_icon(self):
        return PLATFORM_ICONS.get(self.platform, "gamepad-2")

    @property
    def is_boosted(self):
        return self.bumped_at - self.created_at > timezone.timedelta(minutes=1) and timezone.now() - self.bumped_at < timezone.timedelta(days=1)

    @property
    def is_available(self):
        return self.status == self.Status.ACTIVE

    def attr_rows(self):
        """ویژگی‌های اختصاصی برای نمایش: [(icon, label, value)]"""
        rows = []
        for f in self.game.attribute_schema:
            val = self.attrs.get(f["key"])
            if val in (None, "", False):
                continue
            if f.get("type") == "bool":
                val = "دارد"
            elif f.get("unit"):
                val = f"{val} {f['unit']}"
            rows.append((f.get("icon") or "dot", f["label"], val))
        return rows

    def price_verdict(self):
        """سنجه منصفانه بودن قیمت نسبت به میانه همان بازی."""
        median = self.game.median_price(exclude_pk=self.pk)
        if not median:
            return None
        ratio = self.price / median
        if ratio < 0.85:
            label, tone, pos = "زیر قیمت بازار", "sage", 18
        elif ratio <= 1.15:
            label, tone, pos = "قیمت منصفانه", "warn", 50
        else:
            label, tone, pos = "بالاتر از بازار", "danger", 82
        # موقعیت نشانگر روی نوار ۰ تا ۱۰۰
        pos = max(4, min(96, round(50 + (ratio - 1) * 110)))
        return {"label": label, "tone": tone, "pos": pos, "median": int(median), "ratio": ratio}

    def health(self):
        """شناسنامه اکانت: چک‌لیست سلامت و امتیاز ۰ تا ۱۰۰."""
        items = [
            ("mail-check", "دسترسی ایمیل", self.email_access != self.EmailAccess.NONE, self.get_email_access_display()),
            ("user-round-check", "مالک اول", self.first_owner, "فروشنده سازنده اکانت است" if self.first_owner else "اکانت دست دوم است"),
            ("shield-check", "بدون سابقه بن", self.ban_free, "سابقه بن اعلام نشده" if self.ban_free else "سابقه بن دارد"),
            ("key-round", "تأیید دومرحله‌ای", self.has_2fa, "قابل انتقال به خریدار" if self.has_2fa else "فعال نیست"),
            ("images", "اسکرین‌شات واقعی", self.images.exists(), "تصاویر از داخل بازی" if self.images.exists() else "تصویری ثبت نشده"),
        ]
        weights = [30, 20, 25, 10, 15]
        score = sum(w for w, it in zip(weights, items) if it[2])
        return {"items": items, "score": score}


class ListingImage(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="listings/%Y/%m/")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class Bookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="bookmarks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "listing")
        ordering = ["-created_at"]


class SavedSearch(models.Model):
    """جستجوی ذخیره‌شده؛ با ثبت آگهی جدید مطابق، اعلان ارسال می‌شود."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    title = models.CharField(max_length=100)
    query = models.CharField(max_length=500)  # querystring صفحه آگهی‌ها
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def get_absolute_url(self):
        return reverse("listings:list") + "?" + self.query


class Report(models.Model):
    class Reason(models.TextChoices):
        FAKE = "fake", "اطلاعات اکانت جعلی است"
        STOLEN = "stolen", "اکانت دزدی یا هک‌شده است"
        OUTSIDE = "outside", "درخواست معامله خارج از لوطی"
        PRICE = "price", "قیمت غیرواقعی"
        OTHER = "other", "سایر موارد"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.CharField(max_length=10, choices=Reason.choices)
    text = models.CharField(max_length=300, blank=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Offer(models.Model):
    """پیشنهاد قیمت خریدار برای آگهی‌های توافقی."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار پاسخ"
        ACCEPTED = "accepted", "پذیرفته شد"
        DECLINED = "declined", "رد شد"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="offers")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers")
    amount = models.PositiveBigIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
