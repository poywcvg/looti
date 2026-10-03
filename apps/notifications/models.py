from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        ORDER = "order", "معامله"
        CHAT = "chat", "پیام"
        LISTING = "listing", "آگهی"
        WALLET = "wallet", "کیف پول"
        SEARCH = "search", "جستجوی ذخیره‌شده"
        SYSTEM = "system", "لوطی"

    ICONS = {
        "order": "handshake",
        "chat": "message-circle",
        "listing": "megaphone",
        "wallet": "wallet",
        "search": "bell-ring",
        "system": "info",
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def icon(self):
        return self.ICONS.get(self.kind, "bell")


def notify(user, title, body="", url="", kind="system"):
    if user is None:
        return None
    return Notification.objects.create(user=user, title=title, body=body[:300], url=url, kind=kind)
