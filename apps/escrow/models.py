import secrets

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def _order_code():
    return "GM-" + secrets.token_hex(3).upper()


def calc_fee(price, fee_payer):
    """کارمزد لوطی و سهم هر طرف. خروجی: (fee, buyer_total, seller_payout)"""
    from apps.panel.models import site_conf

    conf = site_conf()
    fee = round(price * conf.fee_percent / 100)
    fee = max(conf.fee_min, min(fee, conf.fee_max))
    fee = int(round(fee, -3))  # گرد به هزار تومان
    if fee_payer == "seller":
        return fee, price, max(price - fee, 0)
    if fee_payer == "split":
        half = fee // 2
        return fee, price + (fee - half), max(price - half, 0)
    return fee, price + fee, price


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "در انتظار پرداخت"
        PAID = "paid", "پرداخت شد؛ منتظر تحویل فروشنده"
        VERIFYING = "verifying", "بررسی اکانت توسط واسط"
        DELIVERED = "delivered", "تحویل به خریدار؛ زمان بررسی"
        COMPLETED = "completed", "تکمیل شد"
        DISPUTED = "disputed", "در حال بررسی مشکل"
        CANCELLED = "cancelled", "لغو شد"
        REFUNDED = "refunded", "پول به خریدار برگشت"

    STEPS = [
        ("pending_payment", "پرداخت امن", "wallet"),
        ("paid", "تحویل به واسط", "package"),
        ("verifying", "بررسی واسط", "scan-search"),
        ("delivered", "بررسی خریدار", "user-check"),
        ("completed", "پرداخت به فروشنده", "badge-check"),
    ]

    code = models.CharField(max_length=10, unique=True, default=_order_code, editable=False)
    listing = models.ForeignKey("listings.Listing", on_delete=models.PROTECT, related_name="orders")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchases")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales")
    mediator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="mediated_orders"
    )
    price = models.PositiveBigIntegerField()
    fee = models.PositiveBigIntegerField()
    fee_payer = models.CharField(max_length=8)
    buyer_total = models.PositiveBigIntegerField()
    seller_payout = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    inspection_deadline = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "سفارش امانی"
        verbose_name_plural = "سفارش‌های امانی"

    def __str__(self):
        return self.code

    def get_absolute_url(self):
        return reverse("escrow:detail", args=[self.code])

    def role_of(self, user):
        if user == self.buyer:
            return "buyer"
        if user == self.seller:
            return "seller"
        if user.is_staff:
            return "mediator"
        return None

    @property
    def is_open(self):
        return self.status not in (self.Status.COMPLETED, self.Status.CANCELLED, self.Status.REFUNDED)

    @property
    def step_index(self):
        keys = [s[0] for s in self.STEPS]
        if self.status in keys:
            return keys.index(self.status)
        if self.status == self.Status.DISPUTED:
            return 3
        return len(keys) if self.status == self.Status.COMPLETED else 0

    def steps(self):
        idx = self.step_index
        done_all = self.status == self.Status.COMPLETED
        return [
            {"key": k, "label": label, "icon": ic, "done": done_all or i < idx, "current": not done_all and i == idx}
            for i, (k, label, ic) in enumerate(self.STEPS)
        ]

    @property
    def seller_deadline(self):
        if self.paid_at:
            from apps.panel.models import site_conf

            return self.paid_at + timezone.timedelta(hours=site_conf().seller_delivery_hours)
        return None

    @property
    def status_tone(self):
        return {
            "completed": "sage",
            "disputed": "danger",
            "cancelled": "muted",
            "refunded": "muted",
            "pending_payment": "warn",
        }.get(self.status, "warn")


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    icon = models.CharField(max_length=30, default="circle-dot")
    text = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


def _fernet():
    return Fernet(settings.CREDENTIALS_KEY.encode())


class Credential(models.Model):
    """اطلاعات ورود اکانت؛ رمزنگاری‌شده و فقط بعد از تأیید واسط برای خریدار قابل مشاهده."""

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="credential")
    blob = models.BinaryField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    verified_at = models.DateTimeField(null=True, blank=True)
    mediator_note = models.CharField(max_length=300, blank=True)

    def set_data(self, data: dict):
        import json

        self.blob = _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode())

    def get_data(self):
        import json

        try:
            return json.loads(_fernet().decrypt(bytes(self.blob)).decode())
        except (InvalidToken, ValueError):
            return {}


class Dispute(models.Model):
    class Reason(models.TextChoices):
        WRONG_INFO = "wrong_info", "مشخصات اکانت با آگهی فرق دارد"
        NO_ACCESS = "no_access", "نمی‌توانم وارد اکانت شوم"
        RECLAIMED = "reclaimed", "فروشنده اکانت را پس گرفته"
        OTHER = "other", "سایر موارد"

    class Status(models.TextChoices):
        OPEN = "open", "در حال بررسی"
        REFUNDED = "refunded", "به نفع خریدار"
        RELEASED = "released", "به نفع فروشنده"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="dispute")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=12, choices=Reason.choices)
    text = models.TextField(max_length=1500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    resolution = models.CharField(max_length=500, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class OrderMessage(models.Model):
    """گفتگوی سه‌طرفه خریدار، فروشنده و واسط داخل سفارش."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
