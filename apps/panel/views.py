"""پنل مدیریت لوطی: آمار، معامله‌ها، کاربران، آگهی‌ها، کارهای منتظر و تنظیمات سایت."""
from datetime import timedelta
from functools import wraps

import jdatetime
from django import forms
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.forms import parse_amount
from apps.accounts.models import User, WalletTransaction
from apps.chat.models import guard
from apps.core.utils import en_digits, fa_digits, format_toman
from apps.escrow import services
from apps.escrow.models import Credential, Dispute, Order, OrderMessage
from apps.escrow.services import EscrowError
from apps.listings.models import Game, Listing, Report
from apps.listings.views import notify_saved_searches
from apps.notifications.models import notify

from .models import AuditLog, SiteConfig, audit, site_conf

S = Order.Status
L = Listing.Status
HELD = [S.PAID, S.VERIFYING, S.DELIVERED, S.DISPUTED]

def staff(view):
    """مهمان → صفحه ورود؛ کاربر عادیِ واردشده → ۴۰۳ (وگرنه ورود و پنل هم‌دیگر را بی‌پایان ریدایرکت می‌کنند)."""
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("accounts:login"))
        if not (request.user.is_active and request.user.is_staff):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return inner


def superuser_only(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return staff(inner)


def _counts():
    return {
        "listings": Listing.objects.filter(status=L.PENDING).count(),
        "verify": Order.objects.filter(status=S.VERIFYING).count(),
        "disputes": Order.objects.filter(status=S.DISPUTED).count(),
        "reports": Report.objects.filter(resolved=False).count(),
    }


def _render(request, template, ctx=None):
    ctx = ctx or {}
    ctx.setdefault("counts", _counts())
    return render(request, template, ctx)


def _page(request, qs, per=20):
    return Paginator(qs, per).get_page(request.GET.get("page"))


def _qs_without_page(request):
    q = request.GET.copy()
    q.pop("page", None)
    return q.urlencode()


def _delta(cur, prev):
    """درصد تغییر نسبت به دوره قبل؛ None یعنی دوره قبل داده نداشت."""
    if not prev:
        return None
    return round((cur - prev) * 100 / prev)


def _series(qs, field, days, agg=None):
    """سری روزانه برای نمودار ستونی: [{label, value, h}] — h درصد ارتفاع ستون."""
    start = timezone.localdate() - timedelta(days=days - 1)
    rows = (
        qs.filter(**{f"{field}__date__gte": start})
        .annotate(d=TruncDate(field))
        .values("d")
        .annotate(v=agg or Count("pk"))
    )
    by_day = {r["d"]: r["v"] or 0 for r in rows}
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=day, locale=jdatetime.FA_LOCALE)
        out.append({"label": fa_digits(jd.strftime("%d %B")), "short": fa_digits(jd.strftime("%d")), "value": by_day.get(day, 0)})
    peak = max((p["value"] for p in out), default=0) or 1
    for p in out:
        p["h"] = max(2, round(p["value"] * 100 / peak)) if p["value"] else 0
    return out


# ════════════════════════════════════════════════════════════ نمای کلی
@staff
def dashboard(request):
    services.auto_complete_due()
    now = timezone.now()
    today = timezone.localdate()
    held = Order.objects.filter(status__in=HELD)
    done_today = Order.objects.filter(status=S.COMPLETED, completed_at__date=today)
    week = _series(Order.objects.filter(status=S.COMPLETED), "completed_at", 14, Sum("price"))
    return _render(request, "panel/dashboard.html", {
        "now": now,
        "held_total": held.aggregate(s=Sum("buyer_total"))["s"] or 0,
        "held_count": held.count(),
        "today_done": done_today.count(),
        "today_fee": done_today.aggregate(s=Sum("fee"))["s"] or 0,
        "today_users": User.objects.filter(date_joined__date=today).count(),
        "active_listings": Listing.objects.filter(status=L.ACTIVE).count(),
        "online": User.objects.filter(last_seen__gte=now - timedelta(minutes=5)).count(),
        "week": week,
        "week_total": sum(p["value"] for p in week),
        "late": Order.objects.filter(status=S.PAID, paid_at__lt=now - timedelta(hours=site_conf().seller_delivery_hours))
        .select_related("listing", "seller")[:6],
        "expiring": Order.objects.filter(status=S.DELIVERED, inspection_deadline__lt=now + timedelta(hours=6))
        .select_related("listing", "buyer")[:6],
        "recent": Order.objects.select_related("listing__game", "buyer", "seller")[:8],
        "activity": AuditLog.objects.select_related("actor")[:8],
    })


# ════════════════════════════════════════════════════════════ آمار
RANGES = [(7, "۷ روز"), (30, "۳۰ روز"), (90, "۹۰ روز")]


@staff
def stats(request):
    try:
        days = int(request.GET.get("d", 30))
    except ValueError:
        days = 30
    days = days if days in dict(RANGES) else 30
    now = timezone.now()
    since, prev_since = now - timedelta(days=days), now - timedelta(days=days * 2)

    done = Order.objects.filter(status=S.COMPLETED)
    cur_done, prev_done = done.filter(completed_at__gte=since), done.filter(completed_at__gte=prev_since, completed_at__lt=since)

    def totals(qs):
        a = qs.aggregate(gmv=Sum("price"), fee=Sum("fee"), n=Count("pk"))
        return {k: v or 0 for k, v in a.items()}

    cur, prev = totals(cur_done), totals(prev_done)
    users_cur = User.objects.filter(date_joined__gte=since).count()
    users_prev = User.objects.filter(date_joined__gte=prev_since, date_joined__lt=since).count()
    listings_cur = Listing.objects.filter(created_at__gte=since).count()
    listings_prev = Listing.objects.filter(created_at__gte=prev_since, created_at__lt=since).count()

    kpis = [
        {"label": "حجم معاملات", "value": format_toman(cur["gmv"]), "unit": "تومان", "icon": "chart-line", "tone": "ember", "delta": _delta(cur["gmv"], prev["gmv"])},
        {"label": "درآمد کارمزد", "value": format_toman(cur["fee"]), "unit": "تومان", "icon": "hand-coins", "tone": "sage", "delta": _delta(cur["fee"], prev["fee"])},
        {"label": "معامله موفق", "value": fa_digits(cur["n"]), "unit": "سفارش", "icon": "badge-check", "tone": "saffron", "delta": _delta(cur["n"], prev["n"])},
        {"label": "کاربر تازه", "value": fa_digits(users_cur), "unit": "نفر", "icon": "user-plus", "tone": "ember", "delta": _delta(users_cur, users_prev)},
        {"label": "آگهی تازه", "value": fa_digits(listings_cur), "unit": "آگهی", "icon": "megaphone", "tone": "saffron", "delta": _delta(listings_cur, listings_prev)},
    ]

    # وضعیت سفارش‌های ثبت‌شده در بازه → نمودار حلقه‌ای
    created = Order.objects.filter(created_at__gte=since)
    status_rows = dict(created.values_list("status").annotate(n=Count("pk")))
    palette = {
        "completed": "var(--color-sage)", "delivered": "var(--color-sage-700)", "verifying": "var(--color-saffron-600)",
        "paid": "var(--color-saffron)", "pending_payment": "var(--color-sand-300)", "disputed": "var(--color-ember)",
        "refunded": "var(--color-ember-200)", "cancelled": "var(--color-espresso-300)",
    }
    total_created = sum(status_rows.values())
    breakdown, acc, stops = [], 0, []
    for key, label in S.choices:
        n = status_rows.get(key, 0)
        if not n:
            continue
        pct = n * 100 / total_created
        stops.append(f"{palette[key]} {acc:.2f}% {acc + pct:.2f}%")
        acc += pct
        breakdown.append({"label": label, "n": n, "pct": round(pct), "color": palette[key]})
    donut = f"conic-gradient({', '.join(stops)})" if stops else "conic-gradient(var(--color-sand) 0 100%)"

    paid_n = created.exclude(status__in=[S.PENDING_PAYMENT, S.CANCELLED]).count()
    disputes_n = Dispute.objects.filter(created_at__gte=since).count()
    avg_close = cur_done.filter(paid_at__isnull=False).aggregate(
        a=Avg(ExpressionWrapper(F("completed_at") - F("paid_at"), output_field=DurationField()))
    )["a"]

    top_games = list(
        Game.objects.filter(listings__orders__in=cur_done).annotate(gmv=Sum("listings__orders__price"), n=Count("listings__orders"))
        .order_by("-gmv")[:6]
    )
    gmax = top_games[0].gmv if top_games else 1
    for g in top_games:
        g.share = round(g.gmv * 100 / gmax)

    top_sellers = (
        User.objects.filter(sales__in=cur_done).annotate(gmv=Sum("sales__price"), n=Count("sales")).order_by("-gmv")[:6]
    )

    return _render(request, "panel/stats.html", {
        "days": days, "ranges": RANGES, "kpis": kpis,
        "gmv_series": _series(done, "completed_at", days, Sum("price")),
        "orders_series": _series(Order.objects.all(), "created_at", days),
        "users_series": _series(User.objects.all(), "date_joined", days),
        "donut": donut, "breakdown": breakdown, "total_created": total_created,
        "funnel": [
            ("سفارش ثبت‌شده", total_created, 100),
            ("پرداخت‌شده", paid_n, round(paid_n * 100 / total_created) if total_created else 0),
            ("تکمیل‌شده", status_rows.get("completed", 0), round(status_rows.get("completed", 0) * 100 / total_created) if total_created else 0),
        ],
        "dispute_rate": round(disputes_n * 100 / paid_n, 1) if paid_n else 0,
        "disputes_n": disputes_n,
        "avg_close_h": round(avg_close.total_seconds() / 3600, 1) if avg_close else None,
        "avg_ticket": round(cur["gmv"] / cur["n"]) if cur["n"] else 0,
        "top_games": top_games, "top_sellers": top_sellers,
        "liability": User.objects.aggregate(s=Sum("wallet_balance"))["s"] or 0,
        "held_total": Order.objects.filter(status__in=HELD).aggregate(s=Sum("buyer_total"))["s"] or 0,
    })


# ════════════════════════════════════════════════════════════ معامله‌ها
ORDER_TABS = [
    ("", "همه", "list"),
    ("open", "باز", "loader"),
    (S.VERIFYING, "بررسی واسط", "scan-search"),
    (S.DISPUTED, "حل مشکل", "scale"),
    (S.COMPLETED, "تکمیل", "badge-check"),
    ("closed", "لغو / برگشت", "circle-x"),
]


@staff
def orders(request):
    tab = request.GET.get("s", "")
    q = en_digits(request.GET.get("q", "")).strip()
    qs = Order.objects.select_related("listing__game", "buyer", "seller")
    base = qs
    if q:
        qs = qs.filter(
            Q(code__icontains=q) | Q(listing__title__icontains=q) | Q(listing__code__iexact=q)
            | Q(buyer__phone__contains=q) | Q(seller__phone__contains=q)
            | Q(buyer__username__icontains=q) | Q(seller__username__icontains=q)
            | Q(buyer__display_name__icontains=q) | Q(seller__display_name__icontains=q)
        )
        base = qs
    if tab == "open":
        qs = qs.filter(status__in=HELD)
    elif tab == "closed":
        qs = qs.filter(status__in=[S.CANCELLED, S.REFUNDED])
    elif tab:
        qs = qs.filter(status=tab)
    tab_counts = {
        "": base.count(),
        "open": base.filter(status__in=HELD).count(),
        S.VERIFYING: base.filter(status=S.VERIFYING).count(),
        S.DISPUTED: base.filter(status=S.DISPUTED).count(),
        S.COMPLETED: base.filter(status=S.COMPLETED).count(),
        "closed": base.filter(status__in=[S.CANCELLED, S.REFUNDED]).count(),
    }
    return _render(request, "panel/orders.html", {
        "page": _page(request, qs), "tab": tab, "q": q, "qs": _qs_without_page(request),
        "tabs": [(k, label, ic, tab_counts[k]) for k, label, ic in ORDER_TABS],
        "sum": qs.aggregate(s=Sum("buyer_total"), f=Sum("fee")),
    })


@staff
def order_detail(request, code):
    o = get_object_or_404(Order.objects.select_related("listing__game", "buyer", "seller", "mediator"), code=code)
    cred = Credential.objects.filter(order=o).first()
    return _render(request, "panel/order_detail.html", {
        "o": o,
        "events": o.events.select_related("actor"),
        "thread": o.messages.select_related("sender"),
        "dispute": Dispute.objects.filter(order=o).select_related("opened_by", "resolved_by").first(),
        "cred": cred,
        "cred_data": cred.get_data() if cred and o.status == S.VERIFYING else None,
        "txs": o.transactions.select_related("user")[:10],
    })


@staff
@require_POST
def order_action(request, code):
    o = get_object_or_404(Order, code=code)
    act = request.POST.get("action")
    note = request.POST.get("note", "").strip()[:500]
    url = reverse("panel:order", args=[o.code])
    try:
        if act == "message":
            if note:
                safe, _ = guard(note)
                OrderMessage.objects.create(order=o, sender=request.user, text=safe)
                for u in {o.buyer, o.seller}:
                    notify(u, f"پیام واسط در سفارش {o.code}", safe[:80], o.get_absolute_url() + "#thread", "order")
                messages.success(request, "پیام در گفتگوی سفارش ثبت شد.")
            return redirect(url + "#thread")
        if act == "extend":
            hours = int(request.POST.get("hours") or 24)
            services.staff_extend(o, request.user, max(1, min(hours, 168)))
            audit(request.user, f"مهلت بررسی سفارش {o.code} را {hours} ساعت تمدید کرد", "timer", url)
            messages.success(request, "مهلت بررسی خریدار تمدید شد.")
            return redirect(url)
        if act in ("approve", "reject"):
            if act == "approve":
                services.mediator_approve(o, request.user, note)
            else:
                services.mediator_reject(o, request.user, note or "اطلاعات ورود کار نکرد؛ لطفاً بررسی و دوباره ثبت کنید.")
            audit(request.user, f"{'تأیید' if act == 'approve' else 'برگشت'} اکانت سفارش {o.code}", "scan-search", url)
            messages.success(request, "نتیجه بررسی ثبت شد.")
            return redirect(url)
        if len(note) < 5:
            messages.error(request, "برای این اقدام دلیل بنویسید (دست‌کم ۵ حرف)؛ در تاریخچه سفارش ثبت می‌شود.")
            return redirect(url)
        if act == "refund":
            services.staff_refund(o, request.user, note)
            audit(request.user, f"سفارش {o.code} را لغو و {format_toman(o.buyer_total)} تومان به خریدار برگرداند", "undo-2", url)
            messages.success(request, "پول به کیف پول خریدار برگشت.")
        elif act == "release":
            services.staff_release(o, request.user, note)
            audit(request.user, f"پول سفارش {o.code} را به فروشنده داد", "banknote", url)
            messages.success(request, "پول به فروشنده رسید.")
        elif act == "cancel":
            services.staff_cancel_unpaid(o, request.user, note)
            audit(request.user, f"سفارش پرداخت‌نشده {o.code} را لغو کرد", "circle-x", url)
            messages.success(request, "سفارش لغو شد.")
    except (EscrowError, ValueError) as e:
        messages.error(request, str(e))
    return redirect(url)


# ════════════════════════════════════════════════════════════ کاربران
USER_TABS = [("", "همه"), ("new", "تازه‌واردها"), ("sellers", "فروشنده‌ها"), ("staff", "کارشناسان"), ("blocked", "بسته")]
USER_SORTS = [("new", "جدیدترین"), ("wallet", "بیشترین موجودی"), ("sales", "بیشترین فروش"), ("seen", "آخرین بازدید")]


@staff
def users(request):
    tab, sort = request.GET.get("s", ""), request.GET.get("o", "new")
    q = en_digits(request.GET.get("q", "")).strip().lstrip("@")
    qs = User.objects.annotate(
        n_sales=Count("sales", filter=Q(sales__status=S.COMPLETED), distinct=True),
        n_listings=Count("listings", filter=Q(listings__status=L.ACTIVE), distinct=True),
    )
    if q:
        qs = qs.filter(Q(phone__contains=q) | Q(username__icontains=q) | Q(display_name__icontains=q) | Q(email__icontains=q))
    if tab == "new":
        qs = qs.filter(date_joined__gte=timezone.now() - timedelta(days=7))
    elif tab == "sellers":
        qs = qs.filter(n_sales__gt=0)
    elif tab == "staff":
        qs = qs.filter(is_staff=True)
    elif tab == "blocked":
        qs = qs.filter(is_active=False)
    qs = qs.order_by({"wallet": "-wallet_balance", "sales": "-n_sales", "seen": F("last_seen").desc(nulls_last=True)}.get(sort, "-date_joined"), "-pk")
    week = timezone.now() - timedelta(days=7)
    return _render(request, "panel/users.html", {
        "page": _page(request, qs), "tab": tab, "sort": sort, "q": q, "qs": _qs_without_page(request),
        "tabs": USER_TABS, "sorts": USER_SORTS,
        "summary": {
            "total": User.objects.count(),
            "new": User.objects.filter(date_joined__gte=week).count(),
            "staff": User.objects.filter(is_staff=True).count(),
            "blocked": User.objects.filter(is_active=False).count(),
            "wallets": User.objects.aggregate(s=Sum("wallet_balance"))["s"] or 0,
        },
    })


@staff
def user_detail(request, pk):
    u = get_object_or_404(User, pk=pk)
    orders_qs = Order.objects.filter(Q(buyer=u) | Q(seller=u)).select_related("listing__game", "buyer", "seller")
    done_sales = u.sales.filter(status=S.COMPLETED)
    return _render(request, "panel/user_detail.html", {
        "u": u,
        "orders": orders_qs[:10],
        "listings": u.listings.select_related("game").prefetch_related("images")[:8],
        "txs": u.transactions.select_related("order")[:12],
        "stats": {
            "sales": done_sales.count(),
            "sales_gmv": done_sales.aggregate(s=Sum("price"))["s"] or 0,
            "purchases": u.purchases.filter(status=S.COMPLETED).count(),
            "open": orders_qs.filter(status__in=HELD).count(),
            "listings": u.listings.count(),
            "reports": Report.objects.filter(listing__seller=u).count(),
            "disputes": Dispute.objects.filter(Q(order__buyer=u) | Q(order__seller=u)).count(),
        },
    })


@staff
@require_POST
def user_action(request, pk):
    u = get_object_or_404(User, pk=pk)
    act = request.POST.get("action")
    url = reverse("panel:user", args=[u.pk])
    me = request.user
    if u == me and act in ("block", "staff"):
        messages.error(request, "این تغییر روی حساب خودتان مجاز نیست.")
        return redirect(url)
    if u.is_superuser and not me.is_superuser:
        raise PermissionDenied
    if act == "block":
        u.is_active = not u.is_active
        u.save(update_fields=["is_active"])
        if not u.is_active:
            # همه نشست‌های فعال کاربر بی‌اعتبار می‌شود (بک‌اند احراز هویت کاربر غیرفعال را نمی‌پذیرد)
            Listing.objects.filter(seller=u, status__in=[L.ACTIVE, L.PENDING]).update(status=L.ARCHIVED)
        audit(me, f"{'باز کردن حساب' if u.is_active else 'بستن حساب'} {u.display_name}", "user-check" if u.is_active else "user-x", url)
        messages.success(request, "حساب فعال شد." if u.is_active else "حساب بسته شد و آگهی‌های فعالش بسته شد.")
    elif act == "staff":
        if not me.is_superuser:
            raise PermissionDenied
        u.is_staff = not u.is_staff
        u.save(update_fields=["is_staff"])
        audit(me, f"{u.display_name} را {'کارشناس کرد' if u.is_staff else 'از کارشناسی برداشت'}", "user-round-cog", url)
        messages.success(request, "نقش کاربر به‌روز شد.")
    elif act == "wallet":
        if not me.is_superuser:
            raise PermissionDenied
        amount = parse_amount(request.POST.get("amount"))
        note = request.POST.get("note", "").strip()[:150]
        sign = -1 if request.POST.get("dir") == "debit" else 1
        if not amount or len(note) < 3:
            messages.error(request, "مبلغ و دلیل اصلاح را وارد کنید.")
            return redirect(url)
        try:
            u.wallet_apply(sign * amount, WalletTransaction.Kind.ADJUST, note)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(url)
        notify(u, "کیف پول شما اصلاح شد", f"{'+' if sign > 0 else '−'}{format_toman(amount)} تومان — {note}", reverse("accounts:wallet"), "wallet")
        audit(me, f"کیف پول {u.display_name}: {'+' if sign > 0 else '−'}{format_toman(amount)} تومان ({note})", "pencil-line", url)
        messages.success(request, "موجودی اصلاح شد.")
    elif act == "notify":
        title = request.POST.get("title", "").strip()[:120]
        body = request.POST.get("body", "").strip()[:300]
        if title:
            notify(u, title, body, "", "system")
            audit(me, f"اعلان «{title}» برای {u.display_name}", "bell-ring", url)
            messages.success(request, "اعلان فرستاده شد.")
    return redirect(url)


# ════════════════════════════════════════════════════════════ آگهی‌ها
LISTING_TABS = [("", "همه"), (L.PENDING, "منتظر تأیید"), (L.ACTIVE, "فعال"), (L.RESERVED, "در معامله"), (L.SOLD, "فروخته"), (L.REJECTED, "رد شده"), (L.ARCHIVED, "بسته‌شده")]


@staff
def listings_all(request):
    tab, game = request.GET.get("s", ""), request.GET.get("g", "")
    q = en_digits(request.GET.get("q", "")).strip()
    qs = Listing.objects.select_related("game", "seller").prefetch_related("images").annotate(n_reports=Count("reports", filter=Q(reports__resolved=False)))
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(code__iexact=q) | Q(seller__phone__contains=q) | Q(seller__username__icontains=q))
    if game:
        qs = qs.filter(game__slug=game)
    base = qs
    if tab:
        qs = qs.filter(status=tab)
    counts = dict(base.order_by().values_list("status").annotate(n=Count("pk")))
    return _render(request, "panel/listings_all.html", {
        "page": _page(request, qs.order_by("-created_at")), "tab": tab, "q": q, "game": game, "qs": _qs_without_page(request),
        "tabs": [(k, label, counts.get(k, 0) if k else sum(counts.values())) for k, label in LISTING_TABS],
        "games": Game.objects.all(),
    })


@staff
@require_POST
def listing_action(request, code):
    listing = get_object_or_404(Listing, code=code)
    act = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()[:200]
    if act == "activate" and listing.status in (L.PENDING, L.REJECTED, L.ARCHIVED):
        was_pending = listing.status == L.PENDING
        listing.status, listing.bumped_at = L.ACTIVE, timezone.now()
        listing.save(update_fields=["status", "bumped_at"])
        notify(listing.seller, "آگهی شما منتشر شد", listing.title, listing.get_absolute_url(), "listing")
        if was_pending:
            notify_saved_searches(listing)
        audit(request.user, f"انتشار آگهی {listing.code}", "check", listing.get_absolute_url())
        messages.success(request, f"آگهی {listing.code} منتشر شد.")
    elif act in ("reject", "archive") and listing.status in (L.PENDING, L.ACTIVE):
        listing.status = L.REJECTED if act == "reject" else L.ARCHIVED
        listing.reject_reason = reason or "مغایرت با قوانین لوطی"
        listing.save(update_fields=["status", "reject_reason"])
        notify(listing.seller, "آگهی شما متوقف شد" if act == "archive" else "آگهی شما نیاز به اصلاح دارد", listing.reject_reason, listing.get_absolute_url(), "listing")
        audit(request.user, f"{'رد' if act == 'reject' else 'توقف'} آگهی {listing.code}: {listing.reject_reason}", "eye-off", listing.get_absolute_url())
        messages.info(request, f"آگهی {listing.code} {'رد' if act == 'reject' else 'متوقف'} شد.")
    else:
        messages.error(request, "این کار در وضعیت فعلی آگهی ممکن نیست.")
    return redirect(request.POST.get("next") or reverse("panel:listings_all"))


# ════════════════════════════════════════════════════════════ کارهای منتظر
@staff
def listings_queue(request):
    items = Listing.objects.filter(status=L.PENDING).select_related("game", "seller").prefetch_related("images")
    return _render(request, "panel/listings.html", {"items": items})


@staff
@require_POST
def listing_decide(request, code):
    listing = get_object_or_404(Listing, code=code, status=L.PENDING)
    if request.POST.get("decision") == "approve":
        listing.status = L.ACTIVE
        listing.bumped_at = timezone.now()
        listing.save(update_fields=["status", "bumped_at"])
        notify(listing.seller, "آگهی شما منتشر شد", listing.title, listing.get_absolute_url(), "listing")
        notify_saved_searches(listing)
        messages.success(request, f"آگهی {listing.code} منتشر شد.")
    else:
        reason = request.POST.get("reason", "").strip() or "مغایرت با قوانین لوطی"
        listing.status = L.REJECTED
        listing.reject_reason = reason[:200]
        listing.save(update_fields=["status", "reject_reason"])
        notify(listing.seller, "آگهی شما نیاز به اصلاح دارد", reason, listing.get_absolute_url(), "listing")
        messages.info(request, f"آگهی {listing.code} رد شد.")
    return redirect("panel:listings")


@staff
def verify_queue(request):
    items = Order.objects.filter(status=S.VERIFYING).select_related("listing__game", "buyer", "seller", "credential")
    rows = [{"o": o, "data": o.credential.get_data() if hasattr(o, "credential") else {}} for o in items]
    return _render(request, "panel/verify.html", {"rows": rows})


@staff
@require_POST
def verify_decide(request, code):
    order = get_object_or_404(Order, code=code)
    note = request.POST.get("note", "").strip()[:300]
    try:
        if request.POST.get("decision") == "approve":
            services.mediator_approve(order, request.user, note)
            messages.success(request, f"اکانت سفارش {order.code} تأیید و به خریدار تحویل شد.")
        else:
            services.mediator_reject(order, request.user, note or "اطلاعات ورود کار نکرد؛ لطفاً بررسی و دوباره ثبت کنید.")
            messages.info(request, f"سفارش {order.code} برای اصلاح به فروشنده برگشت.")
    except EscrowError as e:
        messages.error(request, str(e))
    return redirect("panel:verify")


@staff
def disputes(request):
    items = Order.objects.filter(status=S.DISPUTED).select_related("listing__game", "buyer", "seller", "dispute__opened_by")
    return _render(request, "panel/disputes.html", {"items": items})


@staff
@require_POST
def dispute_decide(request, code):
    order = get_object_or_404(Order, code=code)
    note = request.POST.get("note", "").strip()
    if len(note) < 5:
        messages.error(request, "دلیل تصمیم را بنویسید؛ برای هر دو طرف نمایش داده می‌شود.")
        return redirect("panel:disputes")
    try:
        services.resolve_dispute(order, request.user, request.POST.get("decision"), note[:500])
        audit(request.user, f"تصمیم سفارش {order.code}: {'به نفع خریدار' if request.POST.get('decision') == 'refund' else 'به نفع فروشنده'}", "scale",
              reverse("panel:order", args=[order.code]))
        messages.success(request, f"تصمیم سفارش {order.code} ثبت شد.")
    except EscrowError as e:
        messages.error(request, str(e))
    return redirect("panel:disputes")


@staff
def reports(request):
    items = Report.objects.filter(resolved=False).select_related("listing", "reporter")
    return _render(request, "panel/reports.html", {"items": items})


@staff
@require_POST
def report_decide(request, pk):
    r = get_object_or_404(Report, pk=pk)
    if request.POST.get("decision") == "remove" and r.listing.status == L.ACTIVE:
        r.listing.status = L.REJECTED
        r.listing.reject_reason = r.get_reason_display()
        r.listing.save(update_fields=["status", "reject_reason"])
        notify(r.listing.seller, "آگهی شما به دلیل گزارش کاربران متوقف شد", r.get_reason_display(), r.listing.get_absolute_url(), "listing")
        audit(request.user, f"توقف آگهی {r.listing.code} به دلیل گزارش", "flag", r.listing.get_absolute_url())
    Report.objects.filter(listing=r.listing, resolved=False).update(resolved=True)
    messages.success(request, "گزارش بررسی شد.")
    return redirect("panel:reports")


# ════════════════════════════════════════════════════════════ تنظیمات سایت
class SiteConfigForm(forms.ModelForm):
    class Meta:
        model = SiteConfig
        fields = ["fee_percent", "fee_min", "fee_max", "seller_delivery_hours", "inspection_hours", "listing_auto_approve", "announcement", "announcement_tone"]

    def clean(self):
        data = super().clean()
        if data.get("fee_min") is not None and data.get("fee_max") is not None and data["fee_min"] > data["fee_max"]:
            self.add_error("fee_max", "سقف کارمزد باید از حداقل آن بیشتر باشد.")
        return data


@staff
def site_settings(request):
    conf = site_conf()
    form = SiteConfigForm(instance=conf)
    if request.method == "POST":
        if not request.user.is_superuser:
            raise PermissionDenied
        form = SiteConfigForm(request.POST, instance=conf)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            changed = "، ".join(str(form.fields[f].label) for f in form.changed_data) or "بدون تغییر"
            audit(request.user, f"تغییر تنظیمات سایت: {changed}", "sliders-horizontal", reverse("panel:settings"))
            messages.success(request, "تنظیمات ذخیره شد و همین حالا روی سایت اعمال است.")
            return redirect("panel:settings")
    games = Game.objects.annotate(
        n_active=Count("listings", filter=Q(listings__status=L.ACTIVE)),
        n_sold=Count("listings", filter=Q(listings__status=L.SOLD)),
    )
    return _render(request, "panel/settings.html", {"form": form, "conf": conf, "games": games})


@superuser_only
@require_POST
def game_toggle(request, pk):
    g = get_object_or_404(Game, pk=pk)
    g.is_active = not g.is_active
    g.save(update_fields=["is_active"])
    audit(request.user, f"بازی {g.name} {'فعال' if g.is_active else 'غیرفعال'} شد", "gamepad-2", reverse("panel:settings") + "#games")
    messages.success(request, f"{g.name} {'در بازار نمایش داده می‌شود' if g.is_active else 'از بازار پنهان شد'}.")
    return redirect(reverse("panel:settings") + "#games")


@staff
def activity(request):
    qs = AuditLog.objects.select_related("actor")
    who = request.GET.get("who")
    if who:
        qs = qs.filter(actor_id=who)
    return _render(request, "panel/activity.html", {
        "page": _page(request, qs, 30), "who": who, "qs": _qs_without_page(request),
        "staff_users": User.objects.filter(is_staff=True),
    })


# ════════════════════════════════════════════════════════════ جستجوی سراسری
@staff
def search(request):
    q = en_digits(request.GET.get("q", "")).strip()
    if not q:
        return redirect("panel:dashboard")
    exact = Order.objects.filter(code__iexact=q).first()
    if exact:
        return redirect("panel:order", exact.code)
    qn = q.lstrip("@")
    return _render(request, "panel/search.html", {
        "q": q,
        "orders": Order.objects.filter(Q(code__icontains=q) | Q(listing__title__icontains=q)).select_related("listing__game", "buyer", "seller")[:6],
        "users": User.objects.filter(Q(phone__contains=qn) | Q(username__icontains=qn) | Q(display_name__icontains=qn) | Q(email__icontains=qn))[:8],
        "listings": Listing.objects.filter(Q(title__icontains=q) | Q(code__iexact=q)).select_related("game", "seller")[:6],
    })
