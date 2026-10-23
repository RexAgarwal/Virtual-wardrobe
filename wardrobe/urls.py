from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path

from closet import accounts, views as closet_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('closet.urls')),
    path('login/', login_not_required(auth_views.LoginView.as_view(redirect_authenticated_user=True)), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('signup/', accounts.signup, name='signup'),
    path('media/<path:path>', closet_views.media, name='media'),
]
