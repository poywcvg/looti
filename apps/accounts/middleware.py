from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone


class LastSeenMiddleware:
    """ثبت آخرین بازدید کاربر (حداکثر هر ۲ دقیقه یک‌بار) برای نمایش وضعیت آنلاین."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            now = timezone.now()
            if not user.last_seen or now - user.last_seen > timedelta(minutes=2):
                get_user_model().objects.filter(pk=user.pk).update(last_seen=now)
                user.last_seen = now
        return self.get_response(request)
