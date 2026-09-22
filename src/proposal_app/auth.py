"""OIDC signature/issuer/audience/nonce verification through maintained Authlib."""

import ipaddress
from urllib.parse import urlsplit

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import login, logout
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .models import Identity


def oidc_client():
    if not all(
        (
            settings.OIDC_ISSUER,
            settings.OIDC_CLIENT_ID,
            settings.OIDC_CLIENT_SECRET,
            settings.OIDC_REDIRECT_URI,
        )
    ):
        return None
    oauth = OAuth()
    return oauth.register(
        "entra",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        server_metadata_url=settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile", "code_challenge_method": "S256", "timeout": 15},
    )


class AccessMiddleware:
    """Deny by default, including newly added routes and revoked active sessions."""

    public_paths = {"/login/", "/auth/start/", "/auth/callback/", "/auth/local/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in self.public_paths and (
            not request.user.is_authenticated
            or not request.user.is_active
            or not Identity.objects.filter(user=request.user, allowed=True).exists()
        ):
            return HttpResponse("Authentication required", status=401)
        response = self.get_response(request)
        response["Cache-Control"] = "no-store"
        return response


@require_GET
def login_page(request):
    return render(request, "proposal_app/login.html", {"local_auth": settings.LOCAL_AUTH})


@require_GET
def oidc_start(request):
    client = oidc_client()
    if client is None:
        return HttpResponse("Sign-in is not configured", status=503)
    try:
        return client.authorize_redirect(
            request, settings.OIDC_REDIRECT_URI, prompt="select_account"
        )
    except Exception:
        return HttpResponse("Sign-in unavailable", status=503)


@require_GET
def oidc_callback(request):
    client = oidc_client()
    try:
        if client is None:
            raise ValueError("disabled")
        token = client.authorize_access_token(
            request,
            claims_options={
                "iss": {"essential": True, "value": settings.OIDC_ISSUER},
                "aud": {"essential": True, "value": settings.OIDC_CLIENT_ID},
            },
        )
        claims = token["userinfo"]
        identity = Identity.objects.select_related("user").get(
            issuer=claims["iss"],
            subject=claims["sub"],
            allowed=True,
            user__is_active=True,
        )
        login(request, identity.user, backend="django.contrib.auth.backends.ModelBackend")
    except Exception:
        # Never expose tokens/provider messages. A failed login clears any previous identity.
        logout(request)
        return HttpResponse("Sign-in denied", status=403)
    return HttpResponseRedirect("/")


@require_POST
def local_login(request):
    try:
        loopback = ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")).is_loopback
    except ValueError:
        loopback = False
    host = urlsplit("//" + request.get_host()).hostname
    if (
        settings.MODE != "local"
        or not settings.LOCAL_AUTH
        or not loopback
        or host not in {"127.0.0.1", "localhost", "::1"}
    ):
        return HttpResponse("Local sign-in disabled", status=403)
    identity = Identity.objects.filter(
        issuer="local", subject=request.POST.get("subject"), allowed=True, user__is_active=True
    ).first()
    if identity is None:
        return HttpResponse("Sign-in denied", status=403)
    login(request, identity.user, backend="django.contrib.auth.backends.ModelBackend")
    return HttpResponseRedirect("/")


@require_POST
def sign_out(request):
    logout(request)
    return HttpResponseRedirect("/login/")
