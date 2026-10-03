"""فیلتر و مرتب‌سازی آگهی‌ها؛ مشترک بین صفحه جستجو و «هشدار جستجو»."""
from django.db.models import Q

from apps.core.utils import en_digits, format_toman, parse_int

from .models import PLATFORM_CHOICES, Game, Listing

SORTS = [
    ("new", "تازه‌ترین"),
    ("cheap", "ارزان‌ترین"),
    ("expensive", "گران‌ترین"),
    ("health", "سالم‌ترین"),
]


def apply_filters(qs, params):
    """خروجی: (کوئری‌ست، بازی انتخاب‌شده، برچسب فیلترهای فعال)"""
    chips = []
    game = None
    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(code__iexact=q.upper())
            | Q(game__name__icontains=q) | Q(game__name_en__icontains=q)
        )
        chips.append(("q", f"«{q}»"))
    slug = params.get("game")
    if slug:
        game = Game.objects.filter(slug=slug).first()
        if game:
            qs = qs.filter(game=game)
            chips.append(("game", game.name))
    platform = params.get("platform")
    if platform in dict(PLATFORM_CHOICES):
        # آگهی چندپلتفرمی: اگر در لیست platforms باشد یا پلتفرم اصلی همان باشد
        qs = qs.filter(Q(platform=platform) | Q(platforms__contains=[platform]))
        chips.append(("platform", dict(PLATFORM_CHOICES)[platform]))
    pmin = parse_int(en_digits(params.get("min", "")).replace(",", ""))
    pmax = parse_int(en_digits(params.get("max", "")).replace(",", ""))
    if pmin:
        qs = qs.filter(price__gte=pmin)
        chips.append(("min", f"از {format_toman(pmin)}"))
    if pmax:
        qs = qs.filter(price__lte=pmax)
        chips.append(("max", f"تا {format_toman(pmax)}"))
    if params.get("first_owner") == "1":
        qs = qs.filter(first_owner=True)
        chips.append(("first_owner", "مالک اول"))
    if params.get("email") == "1":
        qs = qs.exclude(email_access=Listing.EmailAccess.NONE)
        chips.append(("email", "با دسترسی ایمیل"))
    if params.get("negotiable") == "1":
        qs = qs.filter(negotiable=True)
        chips.append(("negotiable", "قیمت توافقی"))
    if params.get("trade") == "1":
        qs = qs.filter(open_to_trade=True)
        chips.append(("trade", "قابل معاوضه"))
    if params.get("photos") == "1":
        qs = qs.filter(images__isnull=False).distinct()
        chips.append(("photos", "عکس‌دار"))
    # فیلترهای اختصاصی هر بازی (فقط گزینه‌ای)
    if game:
        for f in game.attribute_schema:
            if f.get("type") == "select":
                val = params.get(f"a_{f['key']}")
                if val and val in f.get("options", []):
                    qs = qs.filter(**{f"attrs__{f['key']}": val})
                    chips.append((f"a_{f['key']}", f"{f['label']}: {val}"))
            elif f.get("type") == "bool" and params.get(f"a_{f['key']}") == "1":
                qs = qs.filter(**{f"attrs__{f['key']}": True})
                chips.append((f"a_{f['key']}", f["label"]))
    sort = params.get("sort", "new")
    if sort == "cheap":
        qs = qs.order_by("price")
    elif sort == "expensive":
        qs = qs.order_by("-price")
    elif sort == "health":
        qs = qs.order_by("-first_owner", "-ban_free", "-has_2fa", "-bumped_at")
    else:
        qs = qs.order_by("-bumped_at")
    return qs, game, chips


def describe(params):
    """عنوان خوانا برای ذخیره جستجو."""
    _, game, chips = apply_filters(Listing.objects.none(), params)
    parts = [c[1] for c in chips if c[0] != "game"]
    head = game.name if game else "همه بازی‌ها"
    return " · ".join([head, *parts])[:100]
