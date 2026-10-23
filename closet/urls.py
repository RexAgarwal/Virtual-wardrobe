from django.urls import path

from . import views

app_name = 'closet'

urlpatterns = [
    path('', views.item_list, name='item_list'),
    path('items/new/', views.item_create, name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('outfits/', views.outfit_list, name='outfit_list'),
    path('outfits/new/', views.outfit_create, name='outfit_create'),
    path('outfits/<int:pk>/', views.outfit_detail, name='outfit_detail'),
    path('outfits/<int:pk>/edit/', views.outfit_edit, name='outfit_edit'),
    path('outfits/<int:pk>/delete/', views.outfit_delete, name='outfit_delete'),
    path('outfits/<int:pk>/wore/', views.outfit_wore, name='outfit_wore'),
    path('outfits/generate/', views.outfit_generate, name='outfit_generate'),
    path('outfits/generate/save/', views.outfit_generate_save, name='outfit_generate_save'),
    path('fit-check/', views.fitcheck_start, name='fitcheck'),
    path('fit-check/add/', views.fitcheck_add, name='fitcheck_add'),
    path('samples/', views.load_sample_pieces, name='samples'),
    path('about/', views.about, name='about'),
    path('plan/', views.planner, name='planner'),
    path('plan/set/', views.planner_set, name='planner_set'),
    path('trips/', views.trip_list, name='trip_list'),
    path('trips/new/', views.trip_create, name='trip_create'),
    path('trips/<int:pk>/', views.trip_detail, name='trip_detail'),
    path('trips/<int:pk>/edit/', views.trip_edit, name='trip_edit'),
    path('trips/<int:pk>/delete/', views.trip_delete, name='trip_delete'),
    path('trips/<int:pk>/toggle/<int:item_pk>/', views.trip_toggle, name='trip_toggle'),
    path('outfits/surprise/', views.outfit_surprise, name='outfit_surprise'),
]
