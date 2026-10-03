import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.hashers import make_password
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.utils import en_digits
from apps.escrow import services
from apps.escrow.models import Order
from apps.escrow.services import EscrowError, auto_complete_due
from apps.listings.models import Listing, Offer

from .forms import AmountForm, LoginIdentityForm, PasswordLoginForm, PhoneForm, ProfileForm, RegisterForm, SetPasswordForm
from .models import OTPCode, Payment, User, WalletTransaction

HELD_STATUSES = [Order.Status.PAID, Order.Status.VERIFYING, Order.Status.DELIVERED, Order.Status.DISPUTED]


def _safe_next(request, fallback="core:home"):
    nxt = request.POST.get("next") or request.GET.get("next") or request.session.get("login_next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
        return nxt
    return fallback


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request))
    form = PhoneForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        request.session.pop("signup", None)
        if User.objects.filter(phone=phone).exists():
            return _start_otp(request, phone)
        # حساب تازه فقط از فرم ثبت‌نام ساخته می‌شود تا نام کاربری و رمز داشته باشد
        messages.info(request, "این شماره هنوز حساب ندارد؛ نام کاربری و رمز بگذار تا حسابت ساخته شود.")
        return render(request, "accounts/login.html", {
            "form": PhoneForm(), "pw_form": PasswordLoginForm(), "reg_form": RegisterForm(initial={"phone": phone}), "mode": "register",
            "next": request.POST.get("next", ""),
        })
    return render(request, "accounts/login.html", {
        "form": form, "pw_form": PasswordLoginForm(), "reg_form": RegisterForm(), "mode": "otp", "next": request.GET.get("next", ""),
    })


def _start_otp(request, phone):
    if OTPCode.recently_sent(phone):
        messages.info(request, "کد قبلی هنوز معتبر است؛ تا یک دقیقه دیگر می‌توانید کد جدید بگیرید.")
    else:
        code = OTPCode.issue(phone)
        if settings.OTP_DEBUG:
            request.session["otp_debug"] = code
    request.session["login_phone"] = phone
    request.session["login_next"] = request.POST.get("next", "")
    return redirect("accounts:verify")


def register_view(request):
    """ثبت‌نام: بعد از فرم، همان مرحله‌ی کد پیامکی؛ حساب فقط با کد درست ساخته می‌شود."""
    if request.user.is_authenticated:
        return redirect(_safe_next(request))
    reg_form = RegisterForm(request.POST or None)
    if request.method == "POST" and reg_form.is_valid():
        data = reg_form.cleaned_data
        request.session["signup"] = {
            "phone": data["phone"], "name": data["display_name"], "username": data["username"], "pw": make_password(data["password"]),
        }
        return _start_otp(request, data["phone"])
    return render(request, "accounts/login.html", {
        "form": PhoneForm(), "pw_form": PasswordLoginForm(), "reg_form": reg_form, "mode": "register",
        "next": request.POST.get("next") or request.GET.get("next", ""),
    }, status=400 if request.method == "POST" else 200)


def _login_fail_keys(request, identifier):
    ident = en_digits(identifier or "").strip().lower()[:254]
    ip = request.META.get("REMOTE_ADDR", "")
    return [f"pwfail:id:{ident}", f"pwfail:ip:{ip}"]


def _login_locked(keys):
    # قفل IP آستانه بالاتری دارد تا یک شبکه مشترک زود بسته نشود
    limit = settings.PASSWORD_LOGIN_MAX_FAILS
    return cache.get(keys[0], 0) >= limit or cache.get(keys[1], 0) >= limit * 4


def _login_fail(keys):
    ttl = settings.PASSWORD_LOGIN_LOCK_MINUTES * 60
    for key in keys:
        cache.add(key, 0, ttl)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, ttl)


def login_password(request):
    """ورود با رمز عبور و موبایل / نام کاربری / ایمیل."""
    if request.user.is_authenticated:
        return redirect(_safe_next(request))
    if request.method != "POST":
        return redirect("accounts:login")
    pw_form = PasswordLoginForm(request.POST)
    if pw_form.is_valid():
        identifier = pw_form.cleaned_data["identifier"]
        keys = _login_fail_keys(request, identifier)
        if _login_locked(keys):
            error = f"تلاش ناموفق زیاد بود؛ {settings.PASSWORD_LOGIN_LOCK_MINUTES} دقیقه دیگر امتحان کن یا با کد پیامکی وارد شو."
        else:
            user = authenticate(request, identifier=identifier, password=pw_form.cleaned_data["password"])
            if user is not None:
                cache.delete(keys[0])
                nxt = _safe_next(request)
                login(request, user)
                request.session.pop("login_next", None)
                messages.success(request, f"خوش برگشتی، {user.display_name}")
                return redirect(nxt)
            _login_fail(keys)
            error = "شناسه یا رمز عبور درست نیست."
    else:
        error = "شناسه و رمز عبور را وارد کن."
    return render(request, "accounts/login.html", {
        "form": PhoneForm(), "pw_form": pw_form, "reg_form": RegisterForm(), "pw_error": error, "mode": "password",
        "next": request.POST.get("next", ""),
    }, status=400)


def verify_view(request):
    phone = request.session.get("login_phone")
    if not phone:
        return redirect("accounts:login")
    error = ""
    if request.method == "POST":
        if "resend" in request.POST:
            if OTPCode.recently_sent(phone):
                error = "برای ارسال دوباره کمی صبر کنید."
            else:
                code = OTPCode.issue(phone)
                if settings.OTP_DEBUG:
                    request.session["otp_debug"] = code
                return redirect("accounts:verify")
        else:
            code = en_digits("".join(request.POST.getlist("d"))).strip()
            ok, error = OTPCode.verify(phone, code)
            if ok:
                user, created = User.objects.get_or_create(phone=phone)
                signup = request.session.pop("signup", None)
                if created and signup and signup.get("phone") == phone:
                    user.display_name = signup["name"]
                    if signup.get("pw"):
                        user.password = signup["pw"]
                    # اگر در فاصله‌ی ثبت‌نام تا تأیید کد کس دیگری همین نام کاربری را گرفته باشد، بعداً از تنظیمات انتخاب می‌شود
                    uname = signup.get("username")
                    if uname and not User.objects.filter(username=uname).exists():
                        user.username = uname
                    user.save()
                if not user.is_active:
                    messages.error(request, "حساب کاربری شما غیرفعال شده است.")
                    return redirect("accounts:login")
                nxt = _safe_next(request)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                # ورود پیامکی تازه = اجازه تعیین رمز بدون رمز فعلی (فراموشی رمز)
                request.session["otp_login_at"] = int(time.time())
                request.session.pop("login_phone", None)
                request.session.pop("login_next", None)
                request.session.pop("otp_debug", None)
                if created and signup:
                    messages.success(request, f"حسابت ساخته شد، {user.display_name}! به لوطی خوش آمدی.")
                    return redirect(nxt)
                if created:
                    messages.success(request, "به لوطی خوش آمدید! یک نام نمایشی برای خودتان انتخاب کنید.")
                    return redirect("accounts:settings")
                messages.success(request, f"خوش برگشتی، {user.display_name}")
                return redirect(nxt)
    debug_code = request.session.get("otp_debug") if settings.OTP_DEBUG else None
    return render(request, "accounts/verify.html", {"phone": phone, "error": error, "debug_code": debug_code})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "از حساب خود خارج شدید.")
    return redirect("core:home")


DASH_TABS = [
    ("listings", "آگهی‌های من", "megaphone"),
    ("purchases", "خریدها", "shopping-bag"),
    ("sales", "فروش‌ها", "hand-coins"),
    ("offers", "پیشنهادها", "message-square-diff"),
    ("bookmarks", "ذخیره‌ها", "bookmark"),
    ("searches", "هشدار جستجو", "bell-ring"),
]


@login_required
def dashboard(request):
    user = request.user
    auto_complete_due(Order.objects.filter(Q(buyer=user) | Q(seller=user)))
    tab = request.GET.get("tab", "listings")
    if tab not in {t[0] for t in DASH_TABS}:
        tab = "listings"
    ctx = {"tab": tab, "tabs": DASH_TABS}
    if tab == "listings":
        status = request.GET.get("status", "")
        qs = user.listings.select_related("game").prefetch_related("images")
        ctx["status_filter"] = status
        ctx["statuses"] = [(s, label, qs.filter(status=s).count()) for s, label in Listing.Status.choices]
        ctx["items"] = qs.filter(status=status) if status else qs
        ctx["boost_price"] = settings.BOOST_PRICE
    elif tab == "purchases":
        ctx["items"] = user.purchases.select_related("listing__game", "seller")
    elif tab == "sales":
        ctx["items"] = user.sales.select_related("listing__game", "buyer")
    elif tab == "offers":
        ctx["received"] = Offer.objects.filter(listing__seller=user).select_related("listing", "buyer")[:30]
        ctx["sent"] = user.offers.select_related("listing")[:30]
    elif tab == "bookmarks":
        ctx["items"] = [
            b.listing for b in user.bookmarks.select_related("listing__game", "listing__seller").prefetch_related("listing__images")
        ]
    elif tab == "searches":
        ctx["items"] = user.saved_searches.all()
    ctx["open_orders"] = (
        Order.objects.filter(Q(buyer=user) | Q(seller=user))
        .exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED, Order.Status.REFUNDED])
        .select_related("listing__game")[:4]
    )
    return render(request, "accounts/dashboard.html", ctx)


@login_required
def settings_view(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تغییرات ذخیره شد.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", _security_ctx(request, {"form": form}))


def _otp_fresh(request):
    at = request.session.get("otp_login_at", 0)
    return time.time() - at < settings.PASSWORD_RESET_WINDOW_MINUTES * 60


def _needs_current(request):
    return request.user.has_usable_password() and not _otp_fresh(request)


def _security_ctx(request, ctx, identity_form=None, password_form=None):
    user = request.user
    ctx.setdefault("form", ProfileForm(instance=user))
    ctx["identity_form"] = identity_form or LoginIdentityForm(instance=user)
    ctx["password_form"] = password_form or SetPasswordForm(user, require_current=_needs_current(request))
    ctx["require_current"] = _needs_current(request)
    return ctx


def _security_url():
    return f"{reverse('accounts:settings')}#security"


@login_required
@require_POST
def settings_identity(request):
    form = LoginIdentityForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "نام کاربری و ایمیل ذخیره شد.")
        return redirect(_security_url())
    request.user.refresh_from_db()
    return render(request, "accounts/settings.html", _security_ctx(request, {}, identity_form=form), status=400)


@login_required
@require_POST
def settings_password(request):
    user = request.user
    had_password = user.has_usable_password()
    form = SetPasswordForm(user, request.POST, require_current=_needs_current(request))
    if form.is_valid():
        form.save()
        update_session_auth_hash(request, user)
        request.session.pop("otp_login_at", None)
        messages.success(request, "رمز عبور عوض شد." if had_password else "رمز عبور تعیین شد؛ از این به بعد با رمز هم می‌توانی وارد شوی.")
        return redirect(_security_url())
    return render(request, "accounts/settings.html", _security_ctx(request, {}, password_form=form), status=400)


@login_required
@require_POST
def settings_password_remove(request):
    """حذف رمز — از آن به بعد فقط ورود پیامکی."""
    user = request.user
    if _needs_current(request) and not user.check_password(request.POST.get("current_password", "")):
        messages.error(request, "برای حذف رمز، رمز فعلی را درست وارد کن.")
    else:
        user.set_unusable_password()
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)
        messages.info(request, "رمز حذف شد؛ ورود فقط با کد پیامکی است.")
    return redirect(_security_url())


@login_required
def wallet(request):
    user = request.user
    page = Paginator(user.transactions.select_related("order"), 12).get_page(request.GET.get("page"))
    held = sum(o.buyer_total for o in user.purchases.filter(status__in=HELD_STATUSES))
    incoming = sum(o.seller_payout for o in user.sales.filter(status__in=HELD_STATUSES))
    return render(request, "accounts/wallet.html", {
        "page": page, "held": held, "incoming": incoming,
        "presets": [100_000, 500_000, 1_000_000, 3_000_000],
    })


@login_required
@require_POST
def deposit(request):
    form = AmountForm(request.POST, max_amount=200_000_000)
    if not form.is_valid():
        messages.error(request, form.errors["amount"][0])
        return redirect("accounts:wallet")
    pay = Payment.objects.create(user=request.user, amount=form.cleaned_data["amount"])
    return redirect("accounts:gateway", token=pay.token)


@login_required
@require_POST
def withdraw(request):
    user = request.user
    if not user.sheba:
        messages.warning(request, "برای برداشت، ابتدا شماره شبا را در تنظیمات ثبت کنید.")
        return redirect("accounts:settings")
    form = AmountForm(request.POST, min_amount=50_000, max_amount=user.wallet_balance)
    if not form.is_valid():
        messages.error(request, form.errors["amount"][0])
        return redirect("accounts:wallet")
    try:
        user.wallet_apply(-form.cleaned_data["amount"], WalletTransaction.Kind.WITHDRAW, f"برداشت به شبا …{user.sheba[-4:]}")
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "درخواست برداشت ثبت شد؛ پول تا یک روز کاری به حسابتان می‌رسد.")
    return redirect("accounts:wallet")


@login_required
def gateway(request, token):
    """درگاه پرداخت آزمایشی؛ در نسخه عملیاتی با درگاه بانکی جایگزین می‌شود."""
    pay = get_object_or_404(Payment.objects.select_related("order__listing"), token=token, user=request.user)
    back = pay.order.get_absolute_url() if pay.order else "accounts:wallet"
    if pay.status != Payment.Status.PENDING:
        return redirect(back)
    if request.method == "POST":
        if request.POST.get("result") != "ok":
            pay.status = Payment.Status.FAILED
            pay.save(update_fields=["status"])
            messages.error(request, "پرداخت لغو شد و مبلغی از حساب شما کم نشد.")
            return redirect(back)
        with transaction.atomic():
            pay = Payment.objects.select_for_update().get(pk=pay.pk)
            if pay.status != Payment.Status.PENDING:
                return redirect(back)
            pay.status = Payment.Status.PAID
            pay.ref_id = str(secrets.randbelow(10**10)).zfill(10)
            pay.save(update_fields=["status", "ref_id"])
            request.user.wallet_apply(pay.amount, WalletTransaction.Kind.DEPOSIT, f"شارژ از درگاه — پیگیری {pay.ref_id}")
        if pay.order:
            try:
                services.pay_from_wallet(pay.order)
                messages.success(request, "پرداخت موفق بود و مبلغ پیش لوطی قفل شد.")
            except (EscrowError, ValueError) as e:
                messages.warning(request, f"کیف پول شارژ شد اما سفارش پرداخت نشد: {e}")
            return redirect(back)
        messages.success(request, "کیف پول با موفقیت شارژ شد.")
        return redirect(back)
    return render(request, "accounts/gateway.html", {"pay": pay})


def profile(request, pk):
    seller = get_object_or_404(User, pk=pk, is_active=True)
    received = seller.reviews_received.all()
    total = received.count()
    stars = [(i, received.filter(rating=i).count()) for i in range(5, 0, -1)]
    return render(request, "accounts/profile.html", {
        "seller": seller,
        "listings": Listing.objects.public().filter(seller=seller),
        "reviews": received.select_related("author", "order__listing")[:20],
        "stars": stars,
        "reviews_total": total,
        "sold": seller.listings.filter(status=Listing.Status.SOLD).count(),
    })
