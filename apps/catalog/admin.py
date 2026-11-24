from django.contrib import admin

from .models import Category, Item, Package, PackageItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_sw", "kind", "slug")
    list_filter = ("kind",)
    search_fields = ("name_en", "name_sw", "slug")
    prepopulated_fields = {"slug": ("name_en",)}


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "kind", "is_alcoholic", "unit_price", "unit", "is_available")
    list_filter = ("kind", "is_alcoholic", "is_available", "category")
    list_select_related = ("vendor",)
    search_fields = ("name", "vendor__business_name")
    autocomplete_fields = ("vendor", "category")


class PackageItemInline(admin.TabularInline):
    model = PackageItem
    extra = 0
    min_num = 1
    validate_min = True
    autocomplete_fields = ("item",)


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "pricing", "price", "min_guests", "is_available")
    list_filter = ("pricing", "is_available")
    list_select_related = ("vendor",)
    search_fields = ("name", "vendor__business_name")
    autocomplete_fields = ("vendor",)
    inlines = (PackageItemInline,)
