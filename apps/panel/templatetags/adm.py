"""قطعه‌های پنل مدیریت: لینک ناوبری، برچسب وضعیت و درصد تغییر."""
from django import template
from django.urls import reverse
from django.utils.html import format_html

from apps.core.templatetags.ui import icon
from apps.core.utils import fa_digits

register = template.Library()

ORDER_STATUS = {
    "pending_payment": ("در انتظار پرداخت", "muted"),
    "paid": ("منتظر تحویل", "warn"),
    "verifying": ("بررسی واسط", "info"),
    "delivered": ("بررسی خریدار", "info"),
    "completed": ("تکمیل", "sage"),
    "disputed": ("گزارش مشکل", "danger"),
    "cancelled": ("لغو", "muted"),
    "refunded": ("برگشت پول", "muted"),
}
LISTING_STATUS = {
    "pending": ("منتظر تأیید", "warn"),
    "active": ("فعال", "sage"),
    "reserved": ("در معامله", "info"),
    "sold": ("فروخته", "muted"),
    "rejected": ("رد شده", "danger"),
    "archived": ("بسته‌شده", "muted"),
}


@register.inclusion_tag("panel/_link.html", takes_context=True)
def adm_link(context, name, label, icon_name, badge=0, tone="", match=""):
    request = context["request"]
    current = getattr(request.resolver_match, "url_name", "")
    names = {name, *filter(None, match.split(","))}
    return {"url": reverse(f"panel:{name}"), "label": label, "icon": icon_name, "badge": badge, "tone": tone, "active": current in names}


@register.simple_tag
def order_status(order):
    label, tone = ORDER_STATUS.get(order.status, (order.get_status_display(), "muted"))
    return format_html('<span class="st is-{}" title="{}"><i aria-hidden="true"></i>{}</span>', tone, order.get_status_display(), label)


@register.simple_tag
def listing_status(listing):
    label, tone = LISTING_STATUS.get(listing.status, (listing.get_status_display(), "muted"))
    return format_html('<span class="st is-{}"><i aria-hidden="true"></i>{}</span>', tone, label)


@register.simple_tag
def delta(value):
    """درصد تغییر نسبت به دوره قبل؛ مثبت سبز، منفی سفالی."""
    if value is None:
        return format_html('<span class="delta is-flat">تازه</span>')
    if value == 0:
        return format_html('<span class="delta is-flat">بدون تغییر</span>')
    up = value > 0
    return format_html('<span class="delta {}">{}{}٪</span>', "is-up" if up else "is-down",
                       icon("trending-up" if up else "trending-down", "size-3.5"), fa_digits(abs(value)))
