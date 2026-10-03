from django.core.management.base import BaseCommand

from apps.escrow.models import Order
from apps.escrow.services import auto_complete_due


class Command(BaseCommand):
    help = "تکمیل خودکار سفارش‌هایی که مهلت بررسی خریدارشان تمام شده (برای cron، مثلاً هر ۱۵ دقیقه)."

    def handle(self, *args, **options):
        before = Order.objects.filter(status=Order.Status.COMPLETED).count()
        auto_complete_due()
        done = Order.objects.filter(status=Order.Status.COMPLETED).count() - before
        self.stdout.write(self.style.SUCCESS(f"{done} order(s) auto-completed."))
