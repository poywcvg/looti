from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.listings.models import Listing
from apps.notifications.models import notify

from .models import Conversation, Message, guard

QUICK_REPLIES = [
    "سلام، اکانت هنوز موجوده؟",
    "امکان ارسال اسکرین‌شات بیشتر از اسکین‌ها هست؟",
    "ایمیل اصلی اکانت تحویل داده می‌شه؟",
    "خرید رو از طریق واسط لوطی انجام می‌دم.",
]


def _conversation(request, pk):
    conv = get_object_or_404(Conversation.objects.select_related("listing__game", "buyer", "seller"), pk=pk)
    if request.user not in (conv.buyer, conv.seller):
        raise Http404
    return conv


def _inbox(user):
    convs = user.conversations_all().select_related("listing__game", "buyer", "seller").prefetch_related("listing__images")
    out = []
    for c in convs:
        out.append({
            "c": c,
            "other": c.other(user),
            "last": c.last_message(),
            "unread": c.messages.filter(is_read=False).exclude(sender=user).count(),
        })
    return out


@login_required
def inbox(request):
    return render(request, "chat/inbox.html", {"items": _inbox(request.user)})


@login_required
@require_POST
def start(request, code):
    listing = get_object_or_404(Listing, code=code)
    if listing.seller == request.user:
        messages.info(request, "این آگهی متعلق به خودتان است.")
        return redirect(listing.get_absolute_url())
    conv, _ = Conversation.objects.get_or_create(listing=listing, buyer=request.user, defaults={"seller": listing.seller})
    return redirect(conv.get_absolute_url())


@login_required
def thread(request, pk):
    conv = _conversation(request, pk)
    conv.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
    msgs = list(conv.messages.select_related("sender"))
    return render(request, "chat/thread.html", {
        "conv": conv, "other": conv.other(request.user), "msgs": msgs,
        "items": _inbox(request.user), "quick": QUICK_REPLIES if not msgs else [],
        "last_id": msgs[-1].pk if msgs else 0,
    })


@login_required
@require_POST
def send(request, pk):
    conv = _conversation(request, pk)
    text = request.POST.get("text", "").strip()[:1000]
    if not text:
        return HttpResponse(status=204)
    safe, flagged = guard(text)
    msg = Message.objects.create(conversation=conv, sender=request.user, text=safe, flagged=flagged)
    Conversation.objects.filter(pk=conv.pk).update(updated_at=timezone.now())
    other = conv.other(request.user)
    if not other.is_online:
        notify(other, f"پیام جدید از {request.user.display_name}", safe[:80], conv.get_absolute_url(), "chat")
    return render(request, "chat/_messages.html", {"msgs": [msg], "me": request.user, "fresh": True})


@login_required
def poll(request, pk):
    conv = _conversation(request, pk)
    after = int(request.GET.get("after", 0) or 0)
    new = list(conv.messages.filter(pk__gt=after).exclude(sender=request.user).select_related("sender"))
    if not new:
        return HttpResponse(status=204)
    Message.objects.filter(pk__in=[m.pk for m in new]).update(is_read=True)
    return render(request, "chat/_messages.html", {"msgs": new, "me": request.user, "fresh": True})
