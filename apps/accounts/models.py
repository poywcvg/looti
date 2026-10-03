import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models, transaction
from django.db.models import Avg, F, Q
from django.utils import timezone
from django.utils.functional import cached_property


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra):
        if not phone:
            raise ValueError("شماره موبایل الزامی است")
        user = self.model(phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("display_name", "پشتیبانی لوطی")
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField("شماره موبایل", max_length=11, unique=True)
    # نام کاربری و ایمیل اختیاری‌اند و فقط برای ورود با رمز به کار می‌روند؛ خالی = NULL تا یکتایی به هم نخورد
    username = models.CharField("نام کاربری", max_length=30, unique=True, null=True, blank=True)
    email = models.EmailField("ایمیل", unique=True, null=True, blank=True)
    display_name = models.CharField("نام نمایشی", max_length=40, blank=True)
    bio = models.CharField("درباره من", max_length=200, blank=True)
    avatar = models.ImageField("تصویر", upload_to="avatars/", blank=True)
    sheba = models.CharField("شماره شبا", max_length=26, blank=True)
    wallet_balance = models.BigIntegerField("موجودی کیف پول (تومان)", default=0)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField("کارشناس/واسط", default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True)

    objects = UserManager()
    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return self.display_name or self.phone

    def save(self, *args, **kwargs):
        if not self.display_name:
            self.display_name = f"کاربر {self.phone[-4:]}"
        self.username = (self.username or "").strip().lower() or None
        self.email = (self.email or "").strip().lower() or None
        super().save(*args, **kwargs)

    # ------------------------------------------------------------ اعتبار
    @property
    def is_online(self):
        return bool(self.last_seen and timezone.now() - self.last_seen < timedelta(minutes=5))

    @cached_property
    def sales_count(self):
        return self.sales.filter(status="completed").count()

    @cached_property
    def purchases_count(self):
        return self.purchases.filter(status="completed").count()

    @cached_property
    def rating(self):
        r = self.reviews_received.aggregate(avg=Avg("rating"))["avg"]
        return round(r, 1) if r else None

    @cached_property
    def reviews_count(self):
        return self.reviews_received.count()

    @cached_property
    def lost_disputes(self):
        from apps.escrow.models import Dispute

        return Dispute.objects.filter(order__seller=self, status=Dispute.Status.REFUNDED).count()

    @cached_property
    def trust_score(self):
        """امتیاز اعتماد ۰ تا ۱۰۰ — ترکیبی از سابقه، رضایت و قدمت."""
        score = 35
        score += min(self.sales_count * 4, 28)
        score += min(self.purchases_count * 2, 8)
        if self.rating:
            score += round((self.rating - 3) * 7)  # ۵ ستاره ← ۱۴+
        age_days = (timezone.now() - self.date_joined).days
        score += min(age_days // 30, 10)
        if self.sheba:
            score += 5
        score -= self.lost_disputes * 15
        return max(5, min(score, 100))

    @property
    def trust_level(self):
        s = self.trust_score
        if s >= 80:
            return ("عالی", "sage")
        if s >= 60:
            return ("خوب", "saffron")
        if s >= 40:
            return ("معمولی", "sand")
        return ("تازه‌وارد", "sand")

    @cached_property
    def badges(self):
        """نشان‌های فروشنده: (آیکن، عنوان، توضیح)"""
        out = [("smartphone", "موبایل تأییدشده", "شماره موبایل با کد یک‌بارمصرف تأیید شده")]
        if self.sales_count >= 10 and (self.rating or 0) >= 4.5:
            out.append(("award", "فروشنده برتر", "بیش از ۱۰ فروش موفق با رضایت بالا"))
        elif self.sales_count >= 3:
            out.append(("badge-check", "فروشنده فعال", "چند معامله موفق از طریق لوطی"))
        if (timezone.now() - self.date_joined).days >= 90:
            out.append(("hourglass", "عضو قدیمی", "بیش از ۳ ماه عضویت"))
        if self.sheba:
            out.append(("landmark", "حساب بانکی ثبت‌شده", "شبا برای برداشت پول ثبت شده"))
        return out

    def conversations_all(self):
        from apps.chat.models import Conversation

        return Conversation.objects.filter(Q(buyer=self) | Q(seller=self))

    # ------------------------------------------------------------ کیف پول
    def wallet_apply(self, amount, kind, description="", order=None):
        """تغییر اتمیک موجودی و ثبت تراکنش. مقدار منفی یعنی برداشت."""
        with transaction.atomic():
            u = User.objects.select_for_update().get(pk=self.pk)
            if amount < 0 and u.wallet_balance + amount < 0:
                raise ValueError("موجودی کیف پول کافی نیست")
            User.objects.filter(pk=self.pk).update(wallet_balance=F("wallet_balance") + amount)
            u.refresh_from_db(fields=["wallet_balance"])
            self.wallet_balance = u.wallet_balance
            return WalletTransaction.objects.create(
                user=self, amount=amount, kind=kind, description=description, order=order, balance_after=u.wallet_balance
            )


class OTPCode(models.Model):
    phone = models.CharField(max_length=11, db_index=True)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    @staticmethod
    def _hash(phone, code):
        return hashlib.sha256(f"{settings.SECRET_KEY}:{phone}:{code}".encode()).hexdigest()

    @classmethod
    def issue(cls, phone):
        code = f"{secrets.randbelow(10000):04d}"
        cls.objects.filter(phone=phone, used=False).update(used=True)
        cls.objects.create(phone=phone, code_hash=cls._hash(phone, code))
        return code

    @classmethod
    def verify(cls, phone, code):
        otp = cls.objects.filter(phone=phone, used=False).order_by("-created_at").first()
        if not otp:
            return False, "وقت کد تمام شده؛ دوباره درخواست کنید."
        if timezone.now() - otp.created_at > timedelta(seconds=settings.OTP_TTL_SECONDS):
            return False, "زمان کد تمام شده؛ کد جدید بگیرید."
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return False, "تعداد تلاش‌ها زیاد بود؛ کد جدید بگیرید."
        if secrets.compare_digest(otp.code_hash, cls._hash(phone, code)):
            otp.used = True
            otp.save(update_fields=["used"])
            return True, ""
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return False, "کد واردشده درست نیست."

    @classmethod
    def recently_sent(cls, phone, seconds=60):
        return cls.objects.filter(phone=phone, created_at__gte=timezone.now() - timedelta(seconds=seconds)).exists()


class WalletTransaction(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "شارژ کیف پول"
        WITHDRAW = "withdraw", "برداشت به حساب"
        ESCROW_HOLD = "escrow_hold", "پرداخت امن"
        ESCROW_RELEASE = "escrow_release", "واریز پول به فروشنده"
        REFUND = "refund", "برگشت پول"
        BOOST = "boost", "نردبان آگهی"
        ADJUST = "adjust", "اصلاح توسط پشتیبانی"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    amount = models.BigIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField(max_length=200, blank=True)
    order = models.ForeignKey("escrow.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")
    balance_after = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "تراکنش"
        verbose_name_plural = "تراکنش‌ها"

    @property
    def icon(self):
        return {
            "deposit": "arrow-down-left",
            "withdraw": "arrow-up-right",
            "escrow_hold": "lock",
            "escrow_release": "lock-open",
            "refund": "undo-2",
            "boost": "rocket",
            "adjust": "pencil-line",
        }.get(self.kind, "circle")


def _token():
    return secrets.token_hex(16)


class Payment(models.Model):
    """پرداخت از طریق درگاه (در این نسخه درگاه آزمایشی)."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        PAID = "paid", "موفق"
        FAILED = "failed", "ناموفق"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    amount = models.BigIntegerField()
    token = models.CharField(max_length=32, unique=True, default=_token)
    order = models.ForeignKey("escrow.Order", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    ref_id = models.CharField(max_length=20, blank=True)
