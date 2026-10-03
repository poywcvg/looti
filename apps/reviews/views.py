from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.escrow.models import Order
from apps.notifications.models import notify

from .models import Review


@login_required
def create(request, order_code):
    order = get_object_or_404(Order.objects.select_related("listing__game", "seller"), code=order_code,
                              buyer=request.user, status=Order.Status.COMPLETED)
    if hasattr(order, "review"):
        messages.info(request, "برای این معامله قبلاً نظر ثبت کرده‌اید.")
        return redirect(order.get_absolute_url())
    error = ""
    if request.method == "POST":
        try:
            rating = int(request.POST.get("rating", 0))
        except ValueError:
            rating = 0
        tags = [t for t in request.POST.getlist("tags") if t in dict(Review.TAGS)]
        if not 1 <= rating <= 5:
            error = "لطفاً با انتخاب ستاره‌ها امتیاز بدهید."
        else:
            Review.objects.create(order=order, author=request.user, seller=order.seller, rating=rating, tags=tags,
                                  text=request.POST.get("text", "").strip()[:500])
            notify(order.seller, "نظر جدید برای شما ثبت شد", f"{rating} از ۵ — {order.listing.title}",
                   reverse("accounts:profile", args=[order.seller_id]), "system")
            messages.success(request, "ممنون! نظر شما به خریداران بعدی کمک می‌کند.")
            return redirect(order.get_absolute_url())
    return render(request, "reviews/create.html", {"o": order, "tags": Review.TAGS, "error": error})
