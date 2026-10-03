import re

from django.conf import settings
from django.db import models
from django.urls import reverse

from apps.core.utils import en_digits

# «محافظ گفتگو»: جلوی ردوبدل کردن راه ارتباطی خارج از لوطی را می‌گیرد
_GUARD_PATTERNS = [
    re.compile(r"(?:\+?98|0)?\s*9\d(?:[\s\-.]*\d){8}"),  # موبایل
    re.compile(r"(?:https?://)?(?:t\.me|telegram\.me|wa\.me|instagram\.com|discord\.gg)/\S+", re.I),
    re.compile(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_.]{3,}"),  # آیدی
    re.compile(r"\b(?:telegram|whatsapp|instagram|tg|insta)\b", re.I),
    re.compile(r"(?:تلگرام|واتساپ|واتس\s?اپ|اینستا(?:گرام)?|ایتا|روبیکا)"),
]
MASK = "[محافظت لوطی]"


def guard(text):
    """متن را پاک‌سازی می‌کند. خروجی: (متن امن، آیا مورد مشکوک داشت)"""
    normalized = en_digits(text)
    flagged = False
    for pat in _GUARD_PATTERNS:
        normalized, n = pat.subn(MASK, normalized)
        flagged = flagged or n > 0
    return (normalized if flagged else text), flagged


class Conversation(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="conversations")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("listing", "buyer")
        ordering = ["-updated_at"]

    def get_absolute_url(self):
        return reverse("chat:thread", args=[self.pk])

    def other(self, user):
        return self.seller if user == self.buyer else self.buyer

    def last_message(self):
        return self.messages.order_by("-created_at").first()


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField(max_length=1000)
    flagged = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
