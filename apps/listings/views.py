from django import forms as dj_forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import WalletTransaction
from apps.notifications.models import notify
from apps.panel.models import site_conf

from .filters import SORTS, apply_filters, describe
from .forms import ListingForm, OfferForm, ReportForm, clean_images
from .models import PLATFORM_CHOICES, Bookmark, Game, Listing, ListingImage, Offer, SavedSearch

PER_PAGE = 12
COMPARE_MAX = 3


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def listing_list(request):
    params = request.GET
    qs, game, chips = apply_filters(Listing.objects.public(), params)
    page = Paginator(qs, PER_PAGE).get_page(params.get("page"))
    base = params.copy()
    base.pop("page", None)
    chip_links = []
    for key, label in chips:
        p = base.copy()
        p.pop(key, None)
        if key == "game":  # فیلترهای اختصاصی بازی هم برداشته شوند
            for k in list(p.keys()):
                if k.startswith("a_"):
                    p.pop(k)
        chip_links.append((label, "?" + p.urlencode()))
    query = base.urlencode()
    saved = None
    if request.user.is_authenticated and query:
        saved = request.user.saved_searches.filter(query=query).first()
    ctx = {
        "page": page, "game": game, "chips": chip_links, "query": query,
        "games": Game.objects.filter(is_active=True), "platforms": PLATFORM_CHOICES, "sorts": SORTS,
        "params": params, "saved": saved,
        "count": page.paginator.count,
        "bookmarked": set(request.user.bookmarks.values_list("listing_id", flat=True)) if request.user.is_authenticated else set(),
    }
    if _is_htmx(request):
        tpl = "listings/_cards_page.html" if params.get("page") else "listings/_results.html"
        return render(request, tpl, ctx)
    return render(request, "listings/list.html", ctx)


def listing_detail(request, code):
    listing = get_object_or_404(Listing.objects.select_related("game", "seller").prefetch_related("images"), code=code)
    user = request.user
    is_owner = user.is_authenticated and user == listing.seller
    if listing.status in (Listing.Status.PENDING, Listing.Status.REJECTED, Listing.Status.ARCHIVED) and not (is_owner or user.is_staff):
        return render(request, "404.html", status=404)
    seen = request.session.setdefault("seen", [])
    if listing.pk not in seen and not is_owner:
        Listing.objects.filter(pk=listing.pk).update(views=F("views") + 1)
        request.session["seen"] = (seen + [listing.pk])[-200:]
    similar = (
        Listing.objects.public().filter(game=listing.game).exclude(pk=listing.pk)
        .order_by("?")[:4]
    )
    my_offer = None
    if user.is_authenticated and not is_owner:
        my_offer = listing.offers.filter(buyer=user).first()
    from apps.escrow.models import calc_fee

    fee, buyer_total, payout = calc_fee(listing.price, listing.fee_payer)
    return render(request, "listings/detail.html", {
        "l": listing,
        "is_owner": is_owner,
        "health": listing.health(),
        "verdict": listing.price_verdict(),
        "similar": similar,
        "fee": fee, "buyer_total": buyer_total, "payout": payout,
        "bookmarked": user.is_authenticated and Bookmark.objects.filter(user=user, listing=listing).exists(),
        "my_offer": my_offer,
        "report_form": ReportForm(),
        "seller_other": Listing.objects.public().filter(seller=listing.seller).exclude(pk=listing.pk).count(),
        "watchers": listing.bookmarks.count(),
    })


@login_required
def create_pick(request):
    games = Game.objects.filter(is_active=True).annotate(
        active_count=Count("listings", filter=Q(listings__status=Listing.Status.ACTIVE))
    )
    return render(request, "listings/create_pick.html", {"games": games})


def _save_images(listing, files, start=0):
    for i, f in enumerate(files):
        ListingImage.objects.create(listing=listing, image=f, order=start + i)


@login_required
def listing_create(request, slug):
    game = get_object_or_404(Game, slug=slug, is_active=True)
    form = ListingForm(request.POST or None, game=game)
    image_error = ""
    if request.method == "POST":
        files = request.FILES.getlist("images")
        try:
            clean_images(files)
        except dj_forms.ValidationError as e:
            image_error = e.messages[0]
        if form.is_valid() and not image_error:
            with transaction.atomic():
                listing = form.save(commit=False)
                listing.seller = request.user
                listing.status = Listing.Status.ACTIVE if site_conf().listing_auto_approve else Listing.Status.PENDING
                listing.save()
                _save_images(listing, files)
            if listing.status == Listing.Status.ACTIVE:
                notify_saved_searches(listing)
                messages.success(request, "آگهی شما منتشر شد. هر خریدی از طریق واسط امن لوطی انجام می‌شود.")
            else:
                messages.success(request, "آگهی ثبت شد و بعد از بررسی کارشناس (معمولاً کمتر از یک ساعت) منتشر می‌شود.")
            return redirect(listing.get_absolute_url())
    return render(request, "listings/form.html", {
        "form": form, "game": game, "image_error": image_error, "fee_percent": site_conf().fee_percent,
        "median": game.median_price(),
    })


@login_required
def listing_edit(request, code):
    listing = get_object_or_404(Listing, code=code, seller=request.user)
    if listing.status in (Listing.Status.RESERVED, Listing.Status.SOLD):
        messages.warning(request, "آگهی در حال معامله یا فروخته‌شده قابل ویرایش نیست.")
        return redirect(listing.get_absolute_url())
    form = ListingForm(request.POST or None, instance=listing, game=listing.game)
    image_error = ""
    if request.method == "POST":
        files = request.FILES.getlist("images")
        remove = [int(x) for x in request.POST.getlist("remove_image") if x.isdigit()]
        keep = listing.images.exclude(pk__in=remove).count()
        try:
            clean_images(files)
            if keep + len(files) > 6:
                raise dj_forms.ValidationError("حداکثر ۶ تصویر مجاز است.")
        except dj_forms.ValidationError as e:
            image_error = e.messages[0]
        if form.is_valid() and not image_error:
            with transaction.atomic():
                listing = form.save(commit=False)
                if listing.status == Listing.Status.REJECTED or not site_conf().listing_auto_approve:
                    listing.status = Listing.Status.ACTIVE if site_conf().listing_auto_approve else Listing.Status.PENDING
                listing.save()
                listing.images.filter(pk__in=remove).delete()
                _save_images(listing, files, start=keep)
            messages.success(request, "تغییرات آگهی ذخیره شد.")
            return redirect(listing.get_absolute_url())
    return render(request, "listings/form.html", {
        "form": form, "game": listing.game, "listing": listing, "image_error": image_error,
        "fee_percent": site_conf().fee_percent, "median": listing.game.median_price(exclude_pk=listing.pk),
    })


@login_required
@require_POST
def listing_archive(request, code):
    listing = get_object_or_404(Listing, code=code, seller=request.user)
    if listing.status == Listing.Status.ACTIVE:
        listing.status = Listing.Status.ARCHIVED
        messages.info(request, "آگهی از دید خریداران پنهان شد.")
    elif listing.status == Listing.Status.ARCHIVED:
        listing.status = Listing.Status.ACTIVE if site_conf().listing_auto_approve else Listing.Status.PENDING
        messages.success(request, "آگهی دوباره فعال شد.")
    listing.save(update_fields=["status"])
    return redirect(request.POST.get("next") or "accounts:dashboard")


@login_required
@require_POST
def listing_boost(request, code):
    """نردبان: آگهی به بالای فهرست می‌رود و یک روز نشان «ویژه» می‌گیرد."""
    listing = get_object_or_404(Listing, code=code, seller=request.user, status=Listing.Status.ACTIVE)
    try:
        request.user.wallet_apply(-settings.BOOST_PRICE, WalletTransaction.Kind.BOOST, f"نردبان آگهی {listing.code}")
    except ValueError:
        messages.warning(request, "موجودی کیف پول برای نردبان کافی نیست؛ ابتدا کیف پول را شارژ کنید.")
        return redirect("accounts:wallet")
    listing.bumped_at = timezone.now()
    listing.save(update_fields=["bumped_at"])
    messages.success(request, "آگهی شما به بالای فهرست رفت و تا ۲۴ ساعت نشان ویژه دارد.")
    return redirect(request.POST.get("next") or listing.get_absolute_url())


@login_required
def saved(request):
    """آگهی‌های ذخیره‌شده کاربر؛ تازه‌ترین ذخیره اول. آگهی‌های فروخته یا بسته‌شده جدا پایین صفحه می‌آیند."""
    items = [b.listing for b in request.user.bookmarks.select_related("listing__game", "listing__seller").prefetch_related("listing__images")]
    games = list({l.game.pk: l.game for l in items}.values())
    game = next((g for g in games if g.slug == request.GET.get("game")), None)
    if game:
        items = [l for l in items if l.game_id == game.pk]
    open_now = (Listing.Status.ACTIVE, Listing.Status.RESERVED)
    return render(request, "listings/saved.html", {
        "count": len(items),
        "items": [l for l in items if l.status in open_now],
        "closed": [l for l in items if l.status not in open_now],
        "games": games, "game": game, "bookmarked": True,
    })

@require_POST
def bookmark_toggle(request, code):
    listing = get_object_or_404(Listing, code=code)
    if not request.user.is_authenticated:
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = f"{reverse('accounts:login')}?next={listing.get_absolute_url()}"
        return resp
    obj, created = Bookmark.objects.get_or_create(user=request.user, listing=listing)
    if not created:
        obj.delete()
    return render(request, "listings/_bookmark_btn.html", {
        "l": listing, "bookmarked": created, "variant": request.POST.get("variant", "icon"),
    })


@require_POST
def compare_toggle(request, code):
    ids = request.session.get("compare", [])
    if code in ids:
        ids.remove(code)
    else:
        if len(ids) >= COMPARE_MAX:
            ids.pop(0)
        ids.append(code)
    request.session["compare"] = ids
    resp = render(request, "listings/_compare_btn.html", {"l": {"code": code}, "compare_ids": ids})
    resp["HX-Trigger"] = "compare-changed"
    return resp


def compare_bar(request):
    return render(request, "partials/compare_bar.html", {"compare_ids": request.session.get("compare", [])})


def compare(request):
    codes = request.session.get("compare", [])
    items = list(Listing.objects.filter(code__in=codes).select_related("game", "seller").prefetch_related("images"))
    items.sort(key=lambda x: codes.index(x.code))
    rows = []
    if items:
        keys = []
        for it in items:
            for f in it.game.attribute_schema:
                if (f["key"], f["label"]) not in keys:
                    keys.append((f["key"], f["label"]))
        rows = [(label, [it.attrs.get(k, "") for it in items]) for k, label in keys]
    if request.GET.get("clear"):
        request.session["compare"] = []
        return redirect("listings:compare")
    cheapest = min((i.price for i in items), default=None)
    return render(request, "listings/compare.html", {
        "items": items, "rows": rows, "cheapest": cheapest,
        "healths": [i.health() for i in items],
    })


@login_required
@require_POST
def save_search(request):
    query = request.POST.get("query", "")[:500]
    if not query:
        messages.info(request, "ابتدا چند فیلتر انتخاب کنید.")
        return redirect("listings:list")
    params = QueryDict(query)
    if request.user.saved_searches.count() >= 10:
        messages.warning(request, "حداکثر ۱۰ هشدار جستجو می‌توانید داشته باشید.")
    else:
        SavedSearch.objects.get_or_create(user=request.user, query=query, defaults={"title": describe(params)})
        messages.success(request, "هشدار ساخته شد؛ آگهی جدید مطابق این جستجو را خبرتان می‌کنیم.")
    return redirect(reverse("listings:list") + "?" + query)


@login_required
@require_POST
def delete_search(request, pk):
    get_object_or_404(SavedSearch, pk=pk, user=request.user).delete()
    messages.info(request, "هشدار جستجو حذف شد.")
    return redirect(request.POST.get("next") or reverse("accounts:dashboard") + "?tab=searches")


@login_required
@require_POST
def report(request, code):
    listing = get_object_or_404(Listing, code=code)
    form = ReportForm(request.POST)
    if form.is_valid():
        r = form.save(commit=False)
        r.listing, r.reporter = listing, request.user
        r.save()
        messages.success(request, "گزارش شما ثبت شد و کارشناس لوطی بررسی می‌کند. ممنون که مراقب جامعه هستید.")
    return redirect(listing.get_absolute_url())


@login_required
@require_POST
def offer(request, code):
    listing = get_object_or_404(Listing, code=code, status=Listing.Status.ACTIVE, negotiable=True)
    if listing.seller == request.user:
        return redirect(listing.get_absolute_url())
    form = OfferForm(request.POST, listing=listing)
    if form.is_valid():
        Offer.objects.filter(listing=listing, buyer=request.user, status=Offer.Status.PENDING).delete()
        o = form.save(commit=False)
        o.listing, o.buyer = listing, request.user
        o.save()
        from apps.core.utils import format_toman

        notify(listing.seller, "پیشنهاد قیمت جدید", f"{format_toman(o.amount)} تومان برای «{listing.title}»",
               reverse("accounts:dashboard") + "?tab=offers", "listing")
        messages.success(request, "پیشنهاد شما برای فروشنده ارسال شد.")
    else:
        messages.error(request, form.errors["amount"][0])
    return redirect(listing.get_absolute_url())


@login_required
@require_POST
def offer_respond(request, pk):
    o = get_object_or_404(Offer, pk=pk, listing__seller=request.user, status=Offer.Status.PENDING)
    accept = request.POST.get("decision") == "accept"
    o.status = Offer.Status.ACCEPTED if accept else Offer.Status.DECLINED
    o.save(update_fields=["status"])
    if accept:
        notify(o.buyer, "پیشنهاد شما پذیرفته شد", f"می‌توانید «{o.listing.title}» را با قیمت توافقی بخرید.",
               reverse("listings:detail", args=[o.listing.code]), "listing")
        messages.success(request, "پیشنهاد پذیرفته شد؛ خریدار می‌تواند با این قیمت پرداخت کند.")
    else:
        notify(o.buyer, "پیشنهاد شما رد شد", f"فروشنده «{o.listing.title}» پیشنهاد را نپذیرفت.", o.listing.get_absolute_url(), "listing")
        messages.info(request, "پیشنهاد رد شد.")
    return redirect(reverse("accounts:dashboard") + "?tab=offers")


def notify_saved_searches(listing):
    """وقتی آگهی منتشر می‌شود، صاحبان هشدارهای مطابق را خبر کن."""
    single = Listing.objects.filter(pk=listing.pk)
    for s in SavedSearch.objects.exclude(user=listing.seller).select_related("user")[:500]:
        qs, _, _ = apply_filters(single, QueryDict(s.query))
        if qs.exists():
            notify(s.user, "آگهی جدید مطابق جستجوی شما", f"{listing.title} — {s.title}", listing.get_absolute_url(), "search")

