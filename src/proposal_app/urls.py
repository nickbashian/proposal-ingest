from django.urls import path

from . import auth, views

urlpatterns = [
    path("login/", auth.login_page),
    path("auth/start/", auth.oidc_start),
    path("auth/callback/", auth.oidc_callback),
    path("auth/local/", auth.local_login),
    path("logout/", auth.sign_out),
    path("", views.home),
    path("collections/<uuid:collection_id>/", views.collection, name="collection"),
    path("collections/<uuid:collection_id>/drafts/", views.new_draft),
    path("jobs/<uuid:object_id>/", views.job),
    path("drafts/<str:kind>/<uuid:object_id>/", views.draft),
    path("drafts/<str:kind>/<uuid:object_id>/<str:action>/", views.draft),
    path("writing/<uuid:object_id>/", views.writing, name="writing"),
    path("artifacts/<uuid:object_id>/", views.artifact, name="artifact"),
]
