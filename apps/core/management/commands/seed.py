"""داده نمایشی لوطی: بازی‌ها، کاربران، آگهی‌ها و چند معامله امانی در مراحل مختلف.

    python manage.py seed           # فقط بازی‌ها (امن برای تولید)
    python manage.py seed --demo    # بازی‌ها + داده نمایشی
    python manage.py seed --demo --reset
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.models import WalletTransaction as WT
from apps.chat.models import Conversation, Message
from apps.escrow import services
from apps.escrow.models import Dispute, Order
from apps.listings.models import Game, Listing, Report
from apps.reviews.models import Review

RANKS_R6 = ["Copper", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Champion"]
RANKS_VAL = ["Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Ascendant", "Immortal", "Radiant"]
RANKS_LOL = ["Iron", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master"]

GAMES = [
    {
        "slug": "fortnite", "name": "فورتنایت", "name_en": "Fortnite", "icon": "swords", "tone": "#7A5BA6",
        "tagline": "اسکین‌های کمیاب، وی‌باکس و بتل‌پس", "platforms": ["pc", "playstation", "xbox", "mobile", "switch", "cross"],
        "attribute_schema": [
            {"key": "skins", "label": "تعداد اسکین", "type": "number", "icon": "shirt"},
            {"key": "vbucks", "label": "وی‌باکس", "type": "number", "unit": "V-Bucks", "icon": "coins"},
            {"key": "og", "label": "اسکین‌های OG", "type": "text", "icon": "sparkles"},
            {"key": "stw", "label": "Save the World", "type": "bool", "icon": "castle"},
        ],
    },
    {
        "slug": "rainbow-six", "name": "رینبو سیکس", "name_en": "Rainbow Six Siege", "icon": "crosshair", "tone": "#3D6B8C",
        "tagline": "رنک، اپراتور و اسکین‌های بلک آیس", "platforms": ["pc", "playstation", "xbox"],
        "attribute_schema": [
            {"key": "rank", "label": "رنک", "type": "select", "options": RANKS_R6, "icon": "medal"},
            {"key": "operators", "label": "اپراتور باز", "type": "number", "icon": "users"},
            {"key": "black_ice", "label": "بلک آیس", "type": "number", "icon": "snowflake"},
            {"key": "credits", "label": "کردیت", "type": "number", "icon": "coins"},
        ],
    },
    {
        "slug": "counter-strike", "name": "کانتر استرایک ۲", "name_en": "Counter-Strike 2", "icon": "target", "tone": "#C27C2C",
        "tagline": "پرایم، فیس‌ایت و اینونتوری اسکین", "platforms": ["pc"],
        "attribute_schema": [
            {"key": "premier", "label": "ریتینگ پریمیر", "type": "number", "icon": "trophy"},
            {"key": "faceit", "label": "لول فیس‌ایت", "type": "select", "options": [str(i) for i in range(1, 11)], "icon": "gauge"},
            {"key": "prime", "label": "پرایم", "type": "bool", "icon": "badge-check"},
            {"key": "inventory", "label": "ارزش اینونتوری", "type": "number", "unit": "دلار", "icon": "package"},
        ],
    },
    {
        "slug": "valorant", "name": "والورانت", "name_en": "Valorant", "icon": "zap", "tone": "#B5473A",
        "tagline": "رنک، ایجنت و اسکین اسلحه", "platforms": ["pc", "playstation", "xbox"],
        "attribute_schema": [
            {"key": "rank", "label": "رنک", "type": "select", "options": RANKS_VAL, "icon": "medal"},
            {"key": "agents", "label": "ایجنت باز", "type": "number", "icon": "users"},
            {"key": "skins", "label": "اسکین اسلحه", "type": "number", "icon": "sword"},
            {"key": "vp", "label": "والورانت پوینت", "type": "number", "unit": "VP", "icon": "coins"},
        ],
    },
    {
        "slug": "cod-mobile", "name": "کالاف دیوتی موبایل", "name_en": "Call of Duty Mobile", "icon": "smartphone", "tone": "#5E6B47",
        "tagline": "اسلحه‌های میتیک و لجندری", "platforms": ["mobile"],
        "attribute_schema": [
            {"key": "mythic", "label": "اسلحه میتیک", "type": "number", "icon": "flame"},
            {"key": "legendary", "label": "آیتم لجندری", "type": "number", "icon": "gem"},
            {"key": "cp", "label": "سی‌پی", "type": "number", "unit": "CP", "icon": "coins"},
        ],
    },
    {
        "slug": "pubg-mobile", "name": "پابجی موبایل", "name_en": "PUBG Mobile", "icon": "backpack", "tone": "#A8763E",
        "tagline": "ایکس‌سوت، تیر کانکرر و یوسی", "platforms": ["mobile"],
        "attribute_schema": [
            {"key": "tier", "label": "تیر", "type": "select", "options": ["Gold", "Platinum", "Diamond", "Crown", "Ace", "Conqueror"], "icon": "medal"},
            {"key": "xsuits", "label": "ایکس‌سوت", "type": "number", "icon": "shirt"},
            {"key": "uc", "label": "یوسی", "type": "number", "unit": "UC", "icon": "coins"},
        ],
    },
    {
        "slug": "clash-of-clans", "name": "کلش آف کلنز", "name_en": "Clash of Clans", "icon": "castle", "tone": "#8C5A3C",
        "tagline": "تاون‌هال مکس و هیروهای قوی", "platforms": ["mobile"],
        "attribute_schema": [
            {"key": "th", "label": "تاون‌هال", "type": "select", "options": [str(i) for i in range(9, 18)], "icon": "castle"},
            {"key": "heroes", "label": "لول هیروها", "type": "text", "icon": "shield"},
            {"key": "gems", "label": "جم", "type": "number", "icon": "gem"},
        ],
    },
    {
        "slug": "gta-online", "name": "جی‌تی‌ای آنلاین", "name_en": "GTA Online", "icon": "car", "tone": "#4F7A5A",
        "tagline": "پول، املاک و ماشین‌های خاص", "platforms": ["pc", "playstation", "xbox"],
        "attribute_schema": [
            {"key": "money", "label": "پول داخل بازی", "type": "number", "unit": "میلیون دلار", "icon": "banknote"},
            {"key": "cars", "label": "تعداد ماشین", "type": "number", "icon": "car"},
            {"key": "business", "label": "بیزینس‌ها", "type": "text", "icon": "building-2"},
        ],
    },
    {
        "slug": "ea-fc", "name": "ای‌ای اف‌سی", "name_en": "EA SPORTS FC", "icon": "trophy", "tone": "#2F6E73",
        "tagline": "تیم آلتیمیت و کوین", "platforms": ["pc", "playstation", "xbox"],
        "attribute_schema": [
            {"key": "rating", "label": "ریتینگ تیم", "type": "number", "icon": "star"},
            {"key": "coins", "label": "کوین", "type": "number", "icon": "coins"},
            {"key": "icons", "label": "آیکون‌های تیم", "type": "text", "icon": "crown"},
        ],
    },
    {
        "slug": "league-of-legends", "name": "لیگ آف لجندز", "name_en": "League of Legends", "icon": "shield-half", "tone": "#9C6B30",
        "tagline": "رنک، چمپیون و اسکین", "platforms": ["pc"],
        "attribute_schema": [
            {"key": "rank", "label": "رنک", "type": "select", "options": RANKS_LOL, "icon": "medal"},
            {"key": "champions", "label": "چمپیون", "type": "number", "icon": "users"},
            {"key": "skins", "label": "اسکین", "type": "number", "icon": "shirt"},
        ],
    },
]

SELLERS = [
    ("09121110001", "آرش گیمر", "از ۲۰۱۸ فورتنایت بازی می‌کنم؛ همه اکانت‌ها مالک اول."),
    ("09121110002", "نیلوفر", "فقط اکانت‌های خودم را می‌فروشم. سؤال داشتید پیام بدید."),
    ("09121110003", "Mahdi.R6", "پلیر رنکد رینبو؛ تحویل سریع."),
    ("09121110004", "سینا", ""),
    ("09121110005", "کیان", "اکانت موبایل، تحویل همان روز."),
    ("09121110006", "رها", "کالکشن‌دار اسکین."),
]
BUYERS = [
    ("09122220001", "امیر"),
    ("09122220002", "پریا"),
    ("09122220003", "Hamed_FPS"),
]
MEDIATOR = ("09120000000", "واسط لوطی")
# ورود به پنل ادمین (/admin/) با همین حساب واسط — شناسه: این نام کاربری یا شماره واسط. فقط برای محیط محلی؛ در سرور واقعی رمز را عوض کنید.
ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "looti-2p8usleouk"
# ورود با رمز برای حساب‌های نمایشی (فقط داده نمایشی) — شناسه: نام کاربری، ایمیل یا موبایل
DEMO_PASSWORD = "gamanat-demo-1404"
DEMO_LOGINS = {"09122220001": ("amir", "amir@example.com"), "09121110001": ("arash", "arash@example.com")}

LISTINGS = [
    ("fortnite", "اکانت فورتنایت ۱۸۰ اسکین با رنگ‌ریکان و بلک نایت", 14_500_000, "cross", 412,
     {"skins": 180, "vbucks": 2300, "og": "Renegade Raider, Black Knight", "stw": True}, True),
    ("fortnite", "فورتنایت ۴۵ اسکین بتل‌پس فصل جاری", 2_200_000, "playstation", 160, {"skins": 45, "vbucks": 800}, False),
    ("fortnite", "اکانت فورتنایت سیو د ورلد + ۷۰ اسکین", 4_800_000, "pc", 240, {"skins": 70, "stw": True}, True),
    ("rainbow-six", "رینبو سیکس دایموند، همه اپراتورها باز", 6_900_000, "pc", 287,
     {"rank": "Diamond", "operators": 72, "black_ice": 14, "credits": 1200}, True),
    ("rainbow-six", "اکانت R6 پلاتینیوم با ۴۰ اپراتور", 2_600_000, "playstation", 120, {"rank": "Platinum", "operators": 40}, False),
    ("counter-strike", "اکانت CS2 پرایم با ۱۸ هزار پریمیر", 3_400_000, "pc", 31,
     {"premier": 18200, "faceit": "8", "prime": True, "inventory": 140}, False),
    ("counter-strike", "سی‌اس۲ فیس‌ایت لول ۱۰ + اینونتوری ۹۰۰ دلاری", 52_000_000, "pc", 40,
     {"premier": 24100, "faceit": "10", "prime": True, "inventory": 900}, True),
    ("valorant", "والورانت ایمورتال ۳ با ۶۰ اسکین", 11_800_000, "pc", 210, {"rank": "Immortal", "agents": 26, "skins": 60}, True),
    ("valorant", "اکانت والورانت گلد، همه ایجنت‌ها", 1_900_000, "pc", 95, {"rank": "Gold", "agents": 26, "skins": 8}, False),
    ("cod-mobile", "کالاف موبایل ۵ میتیک و ۱۲۰ لجندری", 9_200_000, "mobile", 300, {"mythic": 5, "legendary": 120, "cp": 1500}, True),
    ("pubg-mobile", "پابجی کانکرر سیزن قبل با ۳ ایکس‌سوت", 7_400_000, "mobile", 78, {"tier": "Conqueror", "xsuits": 3, "uc": 600}, True),
    ("pubg-mobile", "اکانت پابجی موبایل ایس با اسکین M416 گلاسیر", 3_100_000, "mobile", 70, {"tier": "Ace", "xsuits": 1}, False),
    ("clash-of-clans", "کلش تاون‌هال ۱۶ فول مکس", 5_600_000, "mobile", None, {"th": "16", "heroes": "95/95/70/45", "gems": 4000}, True),
    ("gta-online", "جی‌تی‌ای آنلاین ۸۰۰ میلیون دلار + ۴۰ ماشین", 2_900_000, "pc", 320, {"money": 800, "cars": 40, "business": "Nightclub, Bunker, Agency"}, False),
    ("ea-fc", "تیم آلتیمیت ۸۹ با سه آیکون", 4_300_000, "playstation", None, {"rating": 89, "coins": 250000, "icons": "Ronaldinho, Kaka, Henry"}, False),
    ("league-of-legends", "لیگ آف لجندز امرالد با ۱۴۰ چمپیون", 3_700_000, "pc", 412, {"rank": "Emerald", "champions": 140, "skins": 88}, True),
]

DESCRIPTION = (
    "اکانت شخصی خودم است و از روز اول دست خودم بوده. همه آیتم‌ها در تصاویر مشخص است.\n"
    "تحویل فقط از طریق واسط لوطی انجام می‌شود؛ بعد از تأیید واسط ایمیل و رمز به نام شما تغییر می‌کند.\n"
    "اگر سؤالی دارید داخل چت لوطی بپرسید."
)


class Command(BaseCommand):
    help = "ساخت بازی‌ها و (با --demo) داده نمایشی لوطی"

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="کاربران، آگهی‌ها و سفارش‌های نمایشی")
        parser.add_argument("--reset", action="store_true", help="پاک‌کردن داده نمایشی قبلی")

    def handle(self, *args, demo=False, reset=False, **opts):
        random.seed(7)
        for i, g in enumerate(GAMES):
            Game.objects.update_or_create(slug=g["slug"], defaults={**g, "order": i})
        self.stdout.write(self.style.SUCCESS(f"{len(GAMES)} بازی آماده است."))
        if not demo:
            return
        phones = [p for p, *_ in SELLERS] + [p for p, _ in BUYERS] + [MEDIATOR[0]]
        if reset:
            self._reset(phones)
        elif Listing.objects.filter(seller__phone__in=phones).exists():
            self.stdout.write("داده نمایشی از قبل وجود دارد؛ برای ساخت دوباره --reset بدهید.")
            return
        with transaction.atomic():
            self._demo()

    def _reset(self, phones):
        users = User.objects.filter(phone__in=phones)
        orders = Order.objects.filter(buyer__in=users) | Order.objects.filter(seller__in=users)
        Review.objects.filter(order__in=orders).delete()
        Dispute.objects.filter(order__in=orders).delete()
        WT.objects.filter(user__in=users).delete()
        orders.delete()
        Listing.objects.filter(seller__in=users).delete()
        users.delete()

    def _demo(self):
        now = timezone.now()
        mediator = User.objects.create_user(MEDIATOR[0], ADMIN_PASSWORD, display_name=MEDIATOR[1], username=ADMIN_LOGIN, is_staff=True, is_superuser=True)
        sellers = []
        for i, (phone, name, bio) in enumerate(SELLERS):
            u = User.objects.create_user(phone, display_name=name, bio=bio, date_joined=now - timedelta(days=40 + i * 70))
            u.last_seen = now - timedelta(minutes=random.choice([1, 3, 40, 300]))
            u.save(update_fields=["last_seen"])
            sellers.append(u)
        buyers = []
        for phone, name in BUYERS:
            u = User.objects.create_user(phone, display_name=name, date_joined=now - timedelta(days=120))
            u.wallet_apply(150_000_000, WT.Kind.DEPOSIT, "شارژ نمایشی")
            buyers.append(u)

        for u in User.objects.filter(phone__in=DEMO_LOGINS):
            u.username, u.email = DEMO_LOGINS[u.phone]
            u.set_password(DEMO_PASSWORD)
            u.save()

        games = {g.slug: g for g in Game.objects.all()}
        listings = []
        for i, (slug, title, price, platform, level, attrs, first_owner) in enumerate(LISTINGS):
            _capp = ["telegram", "", "whatsapp", "", "discord", ""][i % 6]
            _cid = ["arash_fn_shop", "", "989121110003", "", "sina.cs", ""][i % 6]
            # نمونه چندتایی: بعضی آگهی‌ها دو پلتفرم و دو راه ارتباطی دارند
            _platforms = [platform, "cross"] if i % 5 == 0 and platform != "cross" else [platform]
            _contacts = [{"app": _capp, "id": _cid}] if _capp and _cid else []
            if i % 7 == 0 and _contacts:
                _contacts = _contacts + [{"app": "instagram", "id": "looti.demo"}]
            l = Listing.objects.create(
                seller=sellers[i % len(sellers)], game=games[slug], title=title, description=DESCRIPTION,
                price=price, platform=platform, platforms=_platforms, level=level, attrs=attrs, region=random.choice(["", "EU", "ME", "Asia"]),
                first_owner=first_owner, ban_free=i % 7 != 3, has_2fa=i % 3 == 0,
                email_access=random.choice(list(Listing.EmailAccess.values)[:2]) if first_owner else Listing.EmailAccess.CHANGEABLE,
                negotiable=i % 4 == 1, fee_payer=random.choice(["buyer", "buyer", "split", "seller"]),
                status=Listing.Status.ACTIVE, views=random.randint(20, 900),
                contact_app=_capp,
                contact_id=_cid,
                contacts=_contacts,
            )
            Listing.objects.filter(pk=l.pk).update(created_at=now - timedelta(hours=i * 9 + 2), bumped_at=now - timedelta(hours=i * 9 + 1))
            l.refresh_from_db()
            listings.append(l)

        # چند آگهی تمام‌شده برای میانه قیمت و سابقه فروشنده
        creds = {"login": "demo_player", "password": "demo-pass", "email": "demo@example.com", "email_password": "demo-mail"}
        for k in range(5):
            l = listings[k * 3]
            o = services.create_order(l, buyers[k % 3])
            services.pay_from_wallet(o)
            services.submit_credentials(o, l.seller, creds)
            services.mediator_approve(o, mediator, "ورود موفق؛ مشخصات با آگهی یکسان است.")
            services.buyer_confirm(o, buyers[k % 3])
            Review.objects.create(
                order=o, author=buyers[k % 3], seller=l.seller, rating=random.choice([5, 5, 4]),
                tags=random.sample(["fast", "honest", "polite", "support"], 2),
                text=random.choice(["خیلی سریع تحویل داد، دقیقاً مثل آگهی.", "معامله راحت و امن، ممنون از واسط.", ""]),
            )
            # آگهی را برای ادامه نمایش دوباره فعال کن (نسخه دوم همان اکانت)
            Listing.objects.filter(pk=l.pk).update(status=Listing.Status.ACTIVE)
            # تاریخ‌ها را در هفته‌های گذشته پخش کن تا نمودارهای پنل معنا داشته باشند
            start = now - timedelta(days=3 + k * 5, hours=random.randint(1, 9))
            Order.objects.filter(pk=o.pk).update(
                created_at=start, paid_at=start + timedelta(minutes=12), delivered_at=start + timedelta(hours=3),
                completed_at=start + timedelta(hours=9),
            )
            o.events.update(created_at=start + timedelta(hours=1))
            o.transactions.update(created_at=start + timedelta(hours=9))

        # یک سفارش در هر مرحله برای امیر (خریدار اول)
        amir = buyers[0]
        flow = [
            (listings[1], "paid"),
            (listings[4], "verifying"),
            (listings[7], "delivered"),
            (listings[10], "disputed"),
        ]
        for l, stage in flow:
            o = services.create_order(l, amir)
            services.pay_from_wallet(o)
            if stage == "paid":
                continue
            services.submit_credentials(o, l.seller, creds)
            if stage == "verifying":
                continue
            services.mediator_approve(o, mediator, "ورود موفق بود.")
            if stage == "disputed":
                services.open_dispute(o, amir, Dispute.Reason.WRONG_INFO, "تعداد ایکس‌سوت‌ها دو تاست، نه سه تا. اسکرین‌شات را در گفتگو فرستادم.")
        services.create_order(listings[13], amir)  # در انتظار پرداخت

        # گفتگو
        conv = Conversation.objects.create(listing=listings[6], buyer=amir, seller=listings[6].seller)
        for who, text in [
            (amir, "سلام، اینونتوری شامل کارامبیت هم هست؟"),
            (listings[6].seller, "سلام، بله کارامبیت داپلر فاز ۲. اسکرینش داخل تصاویر هست."),
            (amir, "عالی، روی ۴۸ تومن هم راضی می‌شید؟"),
        ]:
            Message.objects.create(conversation=conv, sender=who, text=text, is_read=who != amir)

        # گزارش و آگهی منتظر تأیید برای میز واسط
        Report.objects.create(listing=listings[15], reporter=buyers[2], reason=Report.Reason.PRICE, text="قیمت خیلی پایین‌تر از بازار است.")
        Listing.objects.create(
            seller=sellers[1], game=games["valorant"], title="والورانت دایموند ۲ با واندال ریور", description=DESCRIPTION,
            price=4_200_000, platform="pc", platforms=["pc", "xbox"], attrs={"rank": "Diamond", "agents": 22, "skins": 19}, first_owner=True,
        )
        self.stdout.write(self.style.SUCCESS(
            f"داده نمایشی ساخته شد. واسط: {MEDIATOR[0]} · خریدار: {BUYERS[0][0]} · فروشنده: {SELLERS[0][0]} (ورود با کد پیامکی نمایشی)"
        ))
