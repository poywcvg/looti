from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


@login_required
def notification_list(request):
    qs = request.user.notifications.all()
    if request.GET.get("filter") == "unread":
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page": page, "filter": request.GET.get("filter", "")})


@login_required
def dropdown(request):
    return render(request, "notifications/_dropdown.html", {"items": request.user.notifications.all()[:6]})


@login_required
@require_POST
def read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("notifications:list")


@login_required
def open_notification(request, pk):
    n = get_object_or_404(request.user.notifications, pk=pk)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    if n.url and url_has_allowed_host_and_scheme(n.url, {request.get_host()}):
        return redirect(n.url)
    return redirect("notifications:list")
