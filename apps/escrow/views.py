from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import Payment
from apps.chat.models import guard
from apps.listings.models import Listing, Offer
from apps.notifications.models import notify

from . import services
from .models import Dispute, Order, OrderMessage
from .services import EscrowError

S = Order.Status


def _order_for(request, code):
    order = get_object_or_404(Order.objects.select_related("listing__game", "buyer", "seller", "mediator"), code=code)
    role = order.role_of(request.user)
    if role is None:
        raise Http404
    return order, role


@login_required
def order_list(request):
    """/orders/ — فهرست معاملات در داشبورد است."""
    return redirect(f"{reverse('accounts:dashboard')}?tab=purchases")


@login_required
@require_POST
def buy(request, code):
    listing = get_object_or_404(Listing, code=code)
    price = None
    offer_id = request.POST.get("offer")
    if offer_id and offer_id.isdigit():
        offer = Offer.objects.filter(pk=offer_id, listing=listing, buyer=request.user, status=Offer.Status.ACCEPTED).first()
        price = offer.amount if offer else None
    try:
        order = services.create_order(listing, request.user, price)
    except EscrowError as e:
        messages.error(request, str(e))
        return redirect(listing.get_absolute_url())
    return redirect(order.get_absolute_url())


@login_required
def detail(request, code):
    order, role = _order_for(request, code)
    services.auto_complete_due(Order.objects.filter(pk=order.pk))
    order.refresh_from_db()
    credentials = None
    if role == "buyer" and order.status in (S.DELIVERED, S.COMPLETED) and hasattr(order, "credential"):
        credentials = order.credential.get_data()
    has_review = hasattr(order, "review")
    return render(request, "escrow/detail.html", {
        "o": order,
        "role": role,
        "events": order.events.select_related("actor").order_by("-created_at"),
        "thread": order.messages.select_related("sender"),
        "credentials": credentials,
        "shortfall": max(0, order.buyer_total - request.user.wallet_balance),
        "dispute_reasons": Dispute.Reason.choices,
        "dispute": getattr(order, "dispute", None),
        "has_review": has_review,
        "cred_note": order.credential.mediator_note if hasattr(order, "credential") else "",
    })


@login_required
@require_POST
def pay(request, code):
    order, role = _order_for(request, code)
    if role != "buyer":
        raise Http404
    shortfall = order.buyer_total - request.user.wallet_balance
    if shortfall > 0:
        # کسری از درگاه شارژ می‌شود و فوراً پیش لوطی قفل می‌شود
        p = Payment.objects.create(user=request.user, amount=shortfall, order=order)
        return redirect("accounts:gateway", token=p.token)
    try:
        services.pay_from_wallet(order)
        messages.success(request, "مبلغ در حساب امانی لوطی قفل شد. تا تأیید شما، فروشنده پولی دریافت نمی‌کند.")
    except (EscrowError, ValueError) as e:
        messages.error(request, str(e))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def deliver(request, code):
    order, role = _order_for(request, code)
    if role != "seller":
        raise Http404
    data = {
        "login": request.POST.get("login", "").strip()[:150],
        "password": request.POST.get("password", "").strip()[:150],
        "email": request.POST.get("email", "").strip()[:150],
        "email_password": request.POST.get("email_password", "").strip()[:150],
        "recovery": request.POST.get("recovery", "").strip()[:500],
        "notes": request.POST.get("notes", "").strip()[:800],
    }
    if not data["login"] or not data["password"]:
        messages.error(request, "نام کاربری و رمز عبور اکانت الزامی است.")
        return redirect(order.get_absolute_url())
    try:
        services.submit_credentials(order, request.user, data)
        messages.success(request, "اطلاعات رمزنگاری شد و برای واسط ارسال شد. بعد از تأیید، به خریدار تحویل می‌شود.")
    except EscrowError as e:
        messages.error(request, str(e))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def confirm(request, code):
    order, role = _order_for(request, code)
    try:
        services.buyer_confirm(order, request.user)
        messages.success(request, "معامله با موفقیت تمام شد. اکانت مال شماست؛ لطفاً رمزها را همین حالا تغییر دهید.")
    except EscrowError as e:
        messages.error(request, str(e))
        return redirect(order.get_absolute_url())
    return redirect("reviews:create", order_code=order.code)


@login_required
@require_POST
def dispute(request, code):
    order, role = _order_for(request, code)
    reason = request.POST.get("reason")
    text = request.POST.get("text", "").strip()
    if reason not in dict(Dispute.Reason.choices) or len(text) < 10:
        messages.error(request, "دلیل مشکل را انتخاب کنید و توضیح کوتاهی (حداقل ۱۰ حرف) بنویسید.")
        return redirect(order.get_absolute_url())
    try:
        services.open_dispute(order, request.user, reason, text[:1500])
        messages.info(request, "گزارش مشکل ثبت شد. پول تا تصمیم واسط پیش لوطی می‌ماند و هیچ‌کس به آن دسترسی ندارد.")
    except EscrowError as e:
        messages.error(request, str(e))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def cancel(request, code):
    order, role = _order_for(request, code)
    try:
        services.cancel(order, request.user)
        messages.info(request, "سفارش لغو شد.")
    except EscrowError as e:
        messages.error(request, str(e))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def message(request, code):
    """گفتگوی سه‌طرفه خریدار، فروشنده و واسط داخل سفارش."""
    order, role = _order_for(request, code)
    text = request.POST.get("text", "").strip()[:1000]
    if text:
        safe, _ = guard(text)
        msg = OrderMessage.objects.create(order=order, sender=request.user, text=safe)
        for other in {order.buyer, order.seller, order.mediator} - {request.user, None}:
            notify(other, f"پیام جدید در سفارش {order.code}", safe[:80], order.get_absolute_url() + "#thread", "order")
        if request.headers.get("HX-Request"):
            return render(request, "escrow/_message.html", {"m": msg, "me": request.user})
    return redirect(order.get_absolute_url() + "#thread")
