from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Review(models.Model):
    """نظر خریدار درباره فروشنده؛ فقط بعد از معامله تکمیل‌شده."""

    TAGS = [
        ("fast", "تحویل سریع"),
        ("honest", "مطابق آگهی"),
        ("polite", "خوش‌برخورد"),
        ("support", "پشتیبانی بعد از فروش"),
    ]

    order = models.OneToOneField("escrow.Order", on_delete=models.CASCADE, related_name="review")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_written")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_received")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    tags = models.JSONField(default=list, blank=True)
    text = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def tag_labels(self):
        d = dict(self.TAGS)
        return [d[t] for t in self.tags if t in d]
