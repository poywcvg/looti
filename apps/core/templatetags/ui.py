"""تگ‌ها و فیلترهای عمومی رابط کاربری (در همه قالب‌ها بدون load در دسترس است)."""
import re
from datetime import timedelta
from functools import lru_cache

import jdatetime
from django import template
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.core.utils import fa_digits, format_toman

register = template.Library()

ICON_DIR = settings.BASE_DIR / "static" / "icons"
_svg_open = re.compile(r"<svg[^>]*>", re.S)


@lru_cache(maxsize=512)
def _icon_body(name):
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        path = ICON_DIR / "circle-help.svg"
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    return _svg_open.sub("", raw, count=1).replace("</svg>", "").strip()


@register.simple_tag
def icon(name, cls="size-5", stroke="2", label=""):
    """آیکن‌های Lucide به صورت SVG درون‌خطی: {% icon "shield-check" "size-4 text-ember" %}"""
    aria = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" class="lucide shrink-0 {escape(cls)}" {aria}>'
        f"{_icon_body(name)}</svg>"
    )
    return mark_safe(svg)


# نشان لوطی (همان static/img/brand/looti-mark.svg بدون زمینه): کلاه مخملی کج و سبیل از بناگوش در رفته.
# با currentColor رنگ می‌گیرد؛ نوار کلاه شکاف است تا رنگ کاشی از آن دیده شود. با هاور، لوطی کلاهش را برمی‌دارد (lm-hat) و سبیلش تاب می‌خورد (lm-stache).
LOGO_MARK = (
    '<g transform="rotate(-10 24 21)"><g class="lm-hat">'
    '<path fill-rule="evenodd" d="M15.2 19.1L16.6 12.1C16.9 10.7 18.2 9.9 19.6 10.2C21.3 10.6 22.6 11.7 24 11.7'
    'S26.7 10.6 28.4 10.2C29.8 9.9 31.1 10.7 31.4 12.1L32.8 19.1ZM15.75 16.1H32.25L32.6 17.9H15.4Z"/>'
    '<path d="M9.5 20.7C9.5 19.4 10.6 18.7 12 18.7H36C37.4 18.7 38.5 19.4 38.5 20.7C38.5 22 37.4 22.4 36 22.4H12C10.6 22.4 9.5 22 9.5 20.7Z"/>'
    '</g></g>'
    '<path class="lm-stache" d="M24 27.4C26.2 25 30.4 24.6 33.4 26.8C35.2 28.1 36.9 28.1 38.1 26.7C38.9 25.7 38.7 24.2 37.6 23.8'
    'C40.4 23.1 42.4 25.5 41.6 28.6C40.6 32.6 35.2 35.2 30.4 34C27.7 33.3 25.5 31.9 24 31.6'
    'C22.5 31.9 20.3 33.3 17.6 34C12.8 35.2 7.4 32.6 6.4 28.6C5.6 25.5 7.6 23.1 10.4 23.8C9.3 24.2 9.1 25.7 9.9 26.7C11.1 28.1 12.8 28.1 14.6 26.8C17.6 24.6 21.8 25 24 27.4Z"/>'
)


@register.simple_tag
def logo_mark(cls="size-7"):
    """نشان لوطی درون‌خطی: {% logo_mark "size-7" %}"""
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="currentColor" class="logo-mark shrink-0 {escape(cls)}" aria-hidden="true">'
        f"{LOGO_MARK}</svg>"
    )


@register.filter
def fa(value):
    """ارقام فارسی."""
    if value is None:
        return ""
    return fa_digits(value)


@register.filter
def toman(value):
    return format_toman(value)


@register.filter
def jdate(value, fmt="%d %B %Y"):
    if not value:
        return ""
    if hasattr(value, "astimezone") and timezone.is_aware(value):
        value = timezone.localtime(value)
    fa = jdatetime.FA_LOCALE
    jd = jdatetime.datetime.fromgregorian(datetime=value, locale=fa) if hasattr(value, "hour") else jdatetime.date.fromgregorian(date=value, locale=fa)
    return fa_digits(jd.strftime(fmt))


@register.filter
def jdatetime_fa(value):
    return jdate(value, "%d %B %Y، ساعت %H:%M")


@register.filter
def ago(value):
    """زمان نسبی: «۵ دقیقه پیش»"""
    if not value:
        return ""
    delta = timezone.now() - value
    s = int(delta.total_seconds())
    if s < 60:
        return "لحظاتی پیش"
    if s < 3600:
        return f"{fa_digits(s // 60)} دقیقه پیش"
    if s < 86400:
        return f"{fa_digits(s // 3600)} ساعت پیش"
    if delta < timedelta(days=2):
        return "دیروز"
    if delta < timedelta(days=30):
        return f"{fa_digits(delta.days)} روز پیش"
    return jdate(value)


@register.filter
def initials(user):
    name = getattr(user, "display_name", "") or ""
    parts = name.split()
    if not parts:
        return "گ"
    return parts[0][0] + (parts[1][0] if len(parts) > 1 else "")


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def mask_phone(phone):
    if not phone or len(phone) < 11:
        return phone
    return fa_digits(f"{phone[:4]}•••{phone[-4:]}")


@register.filter
def percent_of(value, total):
    try:
        return max(0, min(100, round(float(value) * 100 / float(total))))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.simple_tag(takes_context=True)
def tab_active(context):
    """زبانه فعال نوار پایین موبایل بر اساس بخش سایت (نه فقط آدرس دقیق): saved | ads | new | chat | me"""
    match = getattr(context.get("request"), "resolver_match", None)
    if not match:
        return ""
    ns, name = match.namespace, match.url_name
    if ns == "core":
        return "home" if name in ("home", "landing") else ""
    if ns == "listings":
        if name == "saved":
            return "saved"
        return "new" if name in ("create_pick", "create") else "ads"
    if ns == "chat":
        return "chat"
    if ns == "accounts" and name == "dashboard" and context["request"].GET.get("tab") == "bookmarks":
        return "saved"
    if ns in ("accounts", "escrow", "notifications"):
        return "" if name == "profile" else "me"
    return ""


@register.inclusion_tag("components/empty.html")
def empty_state(title, text="", image="empty", action_url="", action_label=""):
    return {"title": title, "text": text, "image": image, "action_url": action_url, "action_label": action_label}


@register.simple_tag
def jyear():
    """سال جاری شمسی برای فوتر."""
    return jdate(timezone.localdate(), "%Y")


# Alert — اقتباس از 21st.dev «alert-1» (React + cva → تگ بلوکی جنگو + CSS)؛ همان variant/appearance/size اصل، با پالت گرم و آیکن‌های لوسید
_ALERT_VARIANTS = ("secondary", "primary", "destructive", "success", "info", "mono", "warning")
_ALERT_ICONS = {"secondary": "info", "primary": "bell", "destructive": "circle-alert", "success": "circle-check",
                "info": "info", "mono": "bell", "warning": "triangle-alert"}


@register.simple_block_tag
def alert(content, variant="secondary", appearance="solid", size="md", title="", icon_name="", close=False,
          action_url="", action_label="", cls=""):
    """{% alert variant="destructive" appearance="light" title="..." close=True %}متن{% endalert %}
    بدون title، خود متن عنوان یک‌خطی می‌شود (مثل دموی اصل). icon_name="none" آیکن را برمی‌دارد."""
    variant = variant if variant in _ALERT_VARIANTS else "secondary"
    appearance = appearance if appearance in ("solid", "outline", "light", "stroke") else "solid"
    size = size if size in ("sm", "md", "lg") else "md"
    name = icon_name or _ALERT_ICONS[variant]
    parts = []
    if name != "none":
        parts.append(f'<div data-slot="alert-icon">{icon(name, "")}</div>')
    if title:
        parts.append(f'<div data-slot="alert-content"><div data-slot="alert-title">{escape(title)}</div>'
                     f'<div data-slot="alert-description">{content}</div></div>')
    else:
        parts.append(f'<div data-slot="alert-title">{content}</div>')
    if action_url and action_label:
        parts.append(f'<div data-slot="alert-toolbar"><a href="{escape(action_url)}">{escape(action_label)}</a></div>')
    attrs = ""
    if close:
        attrs = (' x-data="{ open: true }" x-show="open" x-transition:leave="transition duration-200 ease-exit"'
                 ' x-transition:leave-end="opacity-0 -translate-y-1 scale-[.98]"')
        parts.append(f'<button type="button" data-slot="alert-close" aria-label="بستن" @click="open = false">{icon("x", "")}</button>')
    role = "alert" if variant in ("destructive", "warning") else "status"
    return mark_safe(
        f'<div data-slot="alert" role="{role}" class="alert {escape(cls)}" data-variant="{variant}" '
        f'data-appearance="{appearance}" data-size="{size}"{attrs}>{"".join(parts)}</div>'
    )
