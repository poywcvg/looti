# داده تاریخی: «لوتی» (با ت) در متن‌های ذخیره‌شده دیتابیس را به «لوطی» (با ط) برمی‌گرداند.
# سورس‌کد فعلی همه‌جا «لوطی» است؛ این مایگریشن فقط ردیف‌های قدیمی (سید اولیه، اعلان‌ها،
# رویدادهای سفارش و...) را همسان می‌کند. برگشت‌پذیر نیست (noop).

from django.db import migrations

TEH_VARIANTS = ["\u0644\u0648\u062a\u06cc", "\u0644\u0648\u062a\u064a", "\u0644\u0648\u062a\u0649"]
FIXED = "\u0644\u0648\u0637\u06cc"

TARGETS = [
    ("accounts", "User", ["display_name", "bio"]),
    ("listings", "Listing", ["title", "description"]),
    ("escrow", "Order", ["mediator_note"]),
    ("escrow", "OrderEvent", ["text"]),
    ("escrow", "OrderMessage", ["text"]),
    ("escrow", "Dispute", ["text"]),
    ("notifications", "Notification", ["title", "body"]),
    ("chat", "Message", ["text"]),
    ("reviews", "Review", ["text"]),
    ("panel", "SiteConfig", ["announcement"]),
    ("panel", "AuditLog", ["text"]),
]


def fix_brand(apps, schema_editor):
    for app_label, model_name, field_names in TARGETS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        text_fields = {
            f.name
            for f in model._meta.get_fields()
            if getattr(f, "get_internal_type", None) and f.get_internal_type() in ("CharField", "TextField")
        }
        field_names = [f for f in field_names if f in text_fields]
        if not field_names:
            continue
        for obj in model.objects.all():
            dirty = []
            for fname in field_names:
                val = getattr(obj, fname, "")
                if not isinstance(val, str) or not val:
                    continue
                new = val
                for variant in TEH_VARIANTS:
                    if variant in new:
                        new = new.replace(variant, FIXED)
                if new != val:
                    setattr(obj, fname, new)
                    dirty.append(fname)
            if dirty:
                obj.save(update_fields=dirty)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_plain_labels"),
        ("chat", "0001_initial"),
        ("escrow", "0002_plain_labels"),
        ("listings", "0006_listing_contacts_listing_platforms"),
        ("notifications", "0002_brand_labels"),
        ("panel", "0002_plain_labels"),
        ("reviews", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(fix_brand, migrations.RunPython.noop),
    ]
