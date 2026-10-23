"""Rollout switch: new features start with a few people, then go to everyone by changing one word in settings.

WARDROBE_FEATURES maps a feature name to 'off', 'beta' or 'all'.
'beta' means admins (staff or superuser accounts) and the usernames in WARDROBE_BETA_USERS.
"""
from functools import wraps

from django.conf import settings
from django.http import Http404


def is_beta(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    return user.is_staff or user.is_superuser or user.username.lower() in {u.lower() for u in settings.WARDROBE_BETA_USERS}


def enabled(feature, user):
    mode = settings.WARDROBE_FEATURES.get(feature, 'off')
    if mode == 'all':
        return bool(getattr(user, 'is_authenticated', False))
    return mode == 'beta' and is_beta(user)


def feature_required(feature):
    """Behaves as if the page doesn't exist for anyone the feature isn't switched on for."""
    def wrap(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not enabled(feature, request.user):
                raise Http404
            return view(request, *args, **kwargs)
        return inner
    return wrap


def context(request):
    return {'features': {name: enabled(name, request.user) for name in settings.WARDROBE_FEATURES}}
