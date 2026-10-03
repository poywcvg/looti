"""تنظیمات زنده سایت و دفتر فعالیت کارشناسان."""
from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

_CACHE_KEY = "looti:site-config"


class SiteConfig(models.Model):
    """تک‌ردیفی (pk=1). مقادیر اولیه از settings می‌آید و از پنل مدیریت قابل تغییر است."""

    class Tone(models.TextChoices):
        INFO = "info", "اطلاع‌رسانی"
        WARNING = "warning", "هشدار"
        SUCCESS = "success", "خبر خوب"

    fee_percent = models.PositiveSmallIntegerField("کارمزد لوطی (درصد)", validators=[MinValueValidator(0), MaxValueValidator(30)])
    fee_min = models.PositiveBigIntegerField("حداقل کارمزد (تومان)")
    fee_max = models.PositiveBigIntegerField("سقف کارمزد (تومان)")
    seller_delivery_hours = models.PositiveSmallIntegerField("مهلت تحویل فروشنده (ساعت)", validators=[MinValueValidator(1), MaxValueValidator(240)])
    inspection_hours = models.PositiveSmallIntegerField("مهلت بررسی خریدار (ساعت)", validators=[MinValueValidator(1), MaxValueValidator(720)])
    listing_auto_approve = models.BooleanField("انتشار خودکار آگهی‌ها", default=False)
    announcement = models.CharField("اطلاعیه بالای سایت", max_length=200, blank=True)
    announcement_tone = models.CharField(max_length=8, choices=Tone.choices, default=Tone.INFO)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "تنظیمات سایت"

    @staticmethod
    def _defaults():
        return {
            "fee_percent": settings.ESCROW_FEE_PERCENT,
            "fee_min": settings.ESCROW_FEE_MIN,
            "fee_max": settings.ESCROW_FEE_MAX,
            "seller_delivery_hours": settings.SELLER_DELIVERY_HOURS,
            "inspection_hours": settings.INSPECTION_HOURS,
            "listing_auto_approve": settings.LISTING_AUTO_APPROVE,
        }

    @classmethod
    def load(cls):
        conf = cache.get(_CACHE_KEY)
        if conf is None:
            conf, _ = cls.objects.get_or_create(pk=1, defaults=cls._defaults())
            cache.set(_CACHE_KEY, conf, 300)
        return conf

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(_CACHE_KEY)


def site_conf():
    return SiteConfig.load()


class AuditLog(models.Model):
    """هر کار حساس کارشناس (بستن حساب، اصلاح کیف پول، برگشت پول، تغییر تنظیمات) این‌جا ثبت می‌شود."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    icon = models.CharField(max_length=30, default="circle-dot")
    text = models.CharField(max_length=300)
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "فعالیت کارشناس"
        verbose_name_plural = "فعالیت کارشناسان"


def audit(actor, text, icon="circle-dot", url=""):
    AuditLog.objects.create(actor=actor, text=text[:300], icon=icon, url=url)
