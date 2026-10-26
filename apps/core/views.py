from django.conf import settings
from django.http import Http404, HttpResponseServerError, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .permissions import public
from .services.gallery import build_gallery_context
from .services.health import check_health


@require_GET
@never_cache
@public
def healthz(request):
    healthy = check_health()
    return JsonResponse({"status": "ok" if healthy else "error"}, status=200 if healthy else 503)


@require_GET
@public
def home(request):
    return render(request, "core/landing.html")


@require_GET
@public
def dev_gallery(request):
    if not settings.DEBUG:
        raise Http404
    return render(request, "dev/gallery.html", build_gallery_context())


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    # Rendered without request context so a failing session/DB cannot cause a second error.
    return HttpResponseServerError(render_to_string("errors/500.html"))


def ratelimited(request, exception):
    """``RATELIMIT_VIEW``: shown by django-ratelimit's middleware when a limit trips."""
    return render(request, "errors/429.html", status=429)
