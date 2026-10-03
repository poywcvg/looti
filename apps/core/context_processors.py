from django.conf import settings


def site(request):
    from apps.panel.models import site_conf

    conf = site_conf()
    ctx = {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_NAME_EN": settings.SITE_NAME_EN,
        "SITE_TAGLINE": settings.SITE_TAGLINE,
        "FEE_PERCENT": conf.fee_percent,
        "INSPECTION_HOURS": conf.inspection_hours,
        "SITE_CONF": conf,
        "compare_ids": request.session.get("compare", []) if hasattr(request, "session") else [],
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
        from apps.chat.models import Message

        ctx["unread_messages"] = (
            Message.objects.filter(conversation__in=user.conversations_all(), is_read=False)
            .exclude(sender=user)
            .count()
        )
    return ctx
