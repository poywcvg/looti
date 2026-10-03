from django.db.models import Count, Min, Q, Sum
from django.shortcuts import redirect, render

from apps.accounts.models import User
from apps.escrow.models import Order
from apps.listings.models import Game, Listing
from apps.panel.models import site_conf

SEEN_COOKIE = "gm_seen"


def home(request):
    """لندینگ فقط برای بازدید اول؛ بازدیدکننده‌ی برگشتی یا واردشده مستقیم به همه آگهی‌ها می‌رود."""
    if request.user.is_authenticated or request.COOKIES.get(SEEN_COOKIE):
        return redirect("listings:list")
    return landing(request)


def landing(request):
    """معرفی لوطی — همیشه از /welcome/ در دسترس است."""
    active = Q(listings__status=Listing.Status.ACTIVE)
    games = Game.objects.filter(is_active=True).annotate(
        active_count=Count("listings", filter=active),
        min_price=Min("listings__price", filter=active),
    )
    public = Listing.objects.public()
    done = Order.objects.filter(status=Order.Status.COMPLETED)
    stats = {
        "deals": done.count(),
        "volume": done.aggregate(s=Sum("price"))["s"] or 0,
        "sellers": User.objects.filter(listings__status=Listing.Status.ACTIVE).distinct().count(),
        "listings": public.count(),
    }
    response = render(request, "core/home.html", {
        "games": games,
        "fresh": public[:12],
        "deals": public.filter(negotiable=False).order_by("price")[:4],
        "stats": stats,
        # بازار همین حالا (هیرو): پرآگهی‌ترین بازی‌ها با ارزان‌ترین قیمت
        "market": sorted((g for g in games if g.active_count), key=lambda g: -g.active_count)[:5],
        "seller_hours": site_conf().seller_delivery_hours,
        "inspection_hours": site_conf().inspection_hours,
    })
    response.set_cookie(SEEN_COOKIE, "1", max_age=365 * 24 * 3600, samesite="Lax", httponly=True)
    return response


def how(request):
    return render(request, "core/how.html", {
        "fee_min": site_conf().fee_min,
        "fee_max": site_conf().fee_max,
        "seller_hours": site_conf().seller_delivery_hours,
    })


def rules(request):
    return render(request, "core/rules.html")


def search_suggest(request):
    """نتایج پالت جستجو (Ctrl+K) — HTMX"""
    q = request.GET.get("q", "").strip()
    games, listings = Game.objects.none(), Listing.objects.none()
    if q:
        games = Game.objects.filter(Q(name__icontains=q) | Q(name_en__icontains=q), is_active=True)[:4]
        listings = Listing.objects.public().filter(
            Q(title__icontains=q) | Q(code__iexact=q.upper()) | Q(game__name__icontains=q) | Q(game__name_en__icontains=q)
        )[:6]
    else:
        games = Game.objects.filter(is_active=True)[:6]
    return render(request, "partials/search_suggest.html", {"q": q, "games": games, "listings": listings})


def not_found(request, exception=None):
    return render(request, "404.html", status=404)
