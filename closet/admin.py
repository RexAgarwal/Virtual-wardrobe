from django.contrib import admin

from .models import Item, Outfit, WearLog


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'color', 'season', 'status', 'added')
    list_filter = ('category', 'season', 'status')
    search_fields = ('name', 'brand', 'tags', 'color')


class WearInline(admin.TabularInline):
    model = WearLog
    extra = 0


@admin.register(Outfit)
class OutfitAdmin(admin.ModelAdmin):
    list_display = ('name', 'occasion', 'created')
    filter_horizontal = ('items',)
    inlines = [WearInline]
