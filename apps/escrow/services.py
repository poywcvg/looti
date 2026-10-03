"""منطق معامله امن (امانی). تمام تغییر وضعیت‌ها فقط از این ماژول انجام می‌شود."""
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import WalletTransaction as WT
from apps.core.utils import format_toman
from apps.listings.models import Listing
from apps.notifications.models import notify
from apps.panel.models import site_conf

from .models import Credential, Dispute, Order, OrderEvent, calc_fee

S = Order.Status


class EscrowError(Exception):
    pass


def log(order, text, icon="circle-dot", actor=None):
    OrderEvent.objects.create(order=order, text=text, icon=icon, actor=actor)


def _require(order, *statuses):
    if order.status not in statuses:
        raise EscrowError("این کار در وضعیت فعلی سفارش امکان‌پذیر نیست.")


@transaction.atomic
def create_order(listing, buyer, price=None):
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.seller_id == buyer.pk:
        raise EscrowError("نمی‌توانید آگهی خودتان را بخرید.")
    if listing.status != Listing.Status.ACTIVE:
        raise EscrowError("این آگهی دیگر برای فروش در دسترس نیست.")
    existing = Order.objects.filter(listing=listing, buyer=buyer, status=S.PENDING_PAYMENT).first()
    if existing:
        return existing
    price = price or listing.price
    fee, total, payout = calc_fee(price, listing.fee_payer)
    order = Order.objects.create(
        listing=listing, buyer=buyer, seller=listing.seller, price=price, fee=fee,
        fee_payer=listing.fee_payer, buyer_total=total, seller_payout=payout,
    )
    log(order, "سفارش ثبت شد و منتظر پرداخت است.", "receipt-text", buyer)
    return order


@transaction.atomic
def pay_from_wallet(order):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.PENDING_PAYMENT)
    listing = Listing.objects.select_for_update().get(pk=order.listing_id)
    if listing.status != Listing.Status.ACTIVE:
        raise EscrowError("متأسفانه این اکانت همین الان رزرو شد.")
    order.buyer.wallet_apply(-order.buyer_total, WT.Kind.ESCROW_HOLD, f"سفارش {order.code}", order)
    listing.status = Listing.Status.RESERVED
    listing.save(update_fields=["status"])
    order.status = S.PAID
    order.paid_at = timezone.now()
    order.save(update_fields=["status", "paid_at"])
    # سفارش‌های پرداخت‌نشده دیگر روی همین آگهی لغو شوند
    for other in Order.objects.filter(listing=listing, status=S.PENDING_PAYMENT).exclude(pk=order.pk):
        other.status = S.CANCELLED
        other.save(update_fields=["status"])
        log(other, "اکانت توسط خریدار دیگری رزرو شد.", "circle-x")
    log(order, "مبلغ در حساب امانی لوطی قفل شد. فروشنده پولی دریافت نکرده تا شما اکانت را تأیید کنید.", "lock", order.buyer)
    notify(
        order.seller, "اکانت شما خریدار دارد",
        f"مبلغ پیش لوطی قفل شد. لطفاً تا {site_conf().seller_delivery_hours} ساعت اطلاعات ورود را ثبت کنید.",
        order.get_absolute_url(), "order",
    )
    return order


@transaction.atomic
def submit_credentials(order, user, data):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if user != order.seller:
        raise EscrowError("فقط فروشنده می‌تواند اطلاعات را ثبت کند.")
    _require(order, S.PAID)
    cred, _ = Credential.objects.get_or_create(order=order, defaults={"blob": b""})
    cred.set_data(data)
    cred.verified_at = None
    cred.save()
    order.status = S.VERIFYING
    order.save(update_fields=["status"])
    log(order, "فروشنده اطلاعات ورود را به‌صورت رمزنگاری‌شده به واسط تحویل داد.", "package-check", user)
    notify(order.buyer, "اکانت به واسط تحویل شد", "کارشناس لوطی در حال بررسی اکانت است.", order.get_absolute_url(), "order")
    return order


@transaction.atomic
def mediator_approve(order, mediator, note=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.VERIFYING)
    cred = order.credential
    cred.verified_by = mediator
    cred.verified_at = timezone.now()
    cred.mediator_note = note
    cred.save()
    now = timezone.now()
    order.mediator = mediator
    order.status = S.DELIVERED
    order.delivered_at = now
    order.inspection_deadline = now + timezone.timedelta(hours=site_conf().inspection_hours)
    order.save(update_fields=["mediator", "status", "delivered_at", "inspection_deadline"])
    log(order, "واسط اکانت را بررسی و تأیید کرد؛ اطلاعات ورود برای خریدار باز شد.", "shield-check", mediator)
    notify(
        order.buyer, "اطلاعات اکانت آماده است",
        f"{site_conf().inspection_hours} ساعت فرصت دارید اکانت را بررسی و تأیید کنید.",
        order.get_absolute_url(), "order",
    )
    return order


@transaction.atomic
def mediator_reject(order, mediator, note):
    """اطلاعات ناقص است؛ به فروشنده برمی‌گردد."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.VERIFYING)
    order.status = S.PAID
    order.save(update_fields=["status"])
    log(order, f"واسط اطلاعات را نپذیرفت: {note}", "triangle-alert", mediator)
    notify(order.seller, "اطلاعات اکانت نیاز به اصلاح دارد", note, order.get_absolute_url(), "order")
    return order


def _release(order, actor, text):
    order.seller.wallet_apply(order.seller_payout, WT.Kind.ESCROW_RELEASE, f"فروش {order.listing.title}", order)
    order.status = S.COMPLETED
    order.completed_at = timezone.now()
    order.save(update_fields=["status", "completed_at"])
    order.listing.status = Listing.Status.SOLD
    order.listing.save(update_fields=["status"])
    log(order, text, "badge-check", actor)
    notify(order.seller, "پول فروش به کیف پول شما واریز شد", f"{format_toman(order.seller_payout)} تومان", order.get_absolute_url(), "wallet")


def _refund(order, actor, text):
    order.buyer.wallet_apply(order.buyer_total, WT.Kind.REFUND, f"بازگشت سفارش {order.code}", order)
    order.status = S.REFUNDED
    order.save(update_fields=["status"])
    order.listing.status = Listing.Status.ACTIVE
    order.listing.save(update_fields=["status"])
    log(order, text, "undo-2", actor)
    notify(order.buyer, "مبلغ به کیف پول شما برگشت", f"سفارش {order.code}", order.get_absolute_url(), "wallet")


@transaction.atomic
def buyer_confirm(order, user):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if user != order.buyer:
        raise EscrowError("فقط خریدار می‌تواند تحویل را تأیید کند.")
    _require(order, S.DELIVERED)
    _release(order, user, "خریدار سلامت اکانت را تأیید کرد و پول به فروشنده رسید.")
    return order


@transaction.atomic
def open_dispute(order, user, reason, text):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if user not in (order.buyer, order.seller):
        raise EscrowError("دسترسی ندارید.")
    _require(order, S.PAID, S.VERIFYING, S.DELIVERED)
    Dispute.objects.create(order=order, opened_by=user, reason=reason, text=text)
    order.status = S.DISPUTED
    order.save(update_fields=["status"])
    log(order, "گزارش مشکل ثبت شد؛ پول تا تصمیم واسط قفل می‌ماند.", "scale", user)
    other = order.seller if user == order.buyer else order.buyer
    notify(other, "برای سفارش گزارش مشکل ثبت شد", "واسط لوطی به‌زودی پیگیری می‌کند.", order.get_absolute_url(), "order")
    return order


@transaction.atomic
def resolve_dispute(order, mediator, decision, note):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.DISPUTED)
    d = order.dispute
    d.resolution = note
    d.resolved_by = mediator
    d.resolved_at = timezone.now()
    if decision == "refund":
        d.status = Dispute.Status.REFUNDED
        _refund(order, mediator, f"تصمیم واسط به نفع خریدار: {note}")
    else:
        d.status = Dispute.Status.RELEASED
        _release(order, mediator, f"تصمیم واسط به نفع فروشنده: {note}")
    d.save()
    return order


@transaction.atomic
def cancel(order, user, reason=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == S.PENDING_PAYMENT and user == order.buyer:
        order.status = S.CANCELLED
        order.save(update_fields=["status"])
        log(order, "خریدار سفارش را لغو کرد.", "circle-x", user)
        return order
    if order.status == S.PAID and (user == order.seller or (user == order.buyer and order.seller_deadline < timezone.now())):
        who = "فروشنده از فروش انصراف داد" if user == order.seller else "فروشنده به‌موقع تحویل نداد و خریدار سفارش را لغو کرد"
        _refund(order, user, f"{who}؛ مبلغ کامل به خریدار برگشت.")
        return order
    raise EscrowError("در این مرحله امکان لغو وجود ندارد.")


def auto_complete_due(qs=None):
    """تأیید خودکار سفارش‌هایی که مهلت بررسی خریدار تمام شده."""
    qs = qs if qs is not None else Order.objects.all()
    due = qs.filter(status=S.DELIVERED, inspection_deadline__lt=timezone.now())
    for order in due:
        with transaction.atomic():
            o = Order.objects.select_for_update().get(pk=order.pk)
            if o.status == S.DELIVERED:
                _release(o, None, "مهلت بررسی خریدار تمام شد و معامله به‌صورت خودکار تکمیل شد.")


# ------------------------------------------------------------ اقدام مستقیم مدیریت
@transaction.atomic
def staff_refund(order, staff, note):
    """لغو سفارش توسط مدیریت و برگشت کامل پول به خریدار (قبل از تکمیل)."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.PAID, S.VERIFYING, S.DELIVERED, S.DISPUTED)
    if order.status == S.DISPUTED:
        return resolve_dispute(order, staff, "refund", note)
    _refund(order, staff, f"مدیریت لوطی سفارش را لغو کرد: {note}")
    return order


@transaction.atomic
def staff_release(order, staff, note):
    """واریز پول به فروشنده پیش از پایان مهلت بررسی خریدار."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.DELIVERED, S.DISPUTED)
    if order.status == S.DISPUTED:
        return resolve_dispute(order, staff, "release", note)
    _release(order, staff, f"مدیریت لوطی پول را به فروشنده داد: {note}")
    return order


@transaction.atomic
def staff_cancel_unpaid(order, staff, note):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.PENDING_PAYMENT)
    order.status = S.CANCELLED
    order.save(update_fields=["status"])
    log(order, f"مدیریت لوطی سفارش پرداخت‌نشده را لغو کرد: {note}", "circle-x", staff)
    return order


@transaction.atomic
def staff_extend(order, staff, hours):
    """تمدید مهلت بررسی خریدار."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _require(order, S.DELIVERED)
    order.inspection_deadline = max(order.inspection_deadline or timezone.now(), timezone.now()) + timezone.timedelta(hours=hours)
    order.save(update_fields=["inspection_deadline"])
    log(order, f"مهلت بررسی خریدار {hours} ساعت تمدید شد.", "timer", staff)
    notify(order.buyer, "مهلت بررسی اکانت تمدید شد", f"{hours} ساعت فرصت بیشتر", order.get_absolute_url(), "order")
    return order
