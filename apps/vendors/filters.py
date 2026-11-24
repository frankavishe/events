import django_filters as filters

from .models import ServiceArea, VendorProfile


class VendorFilter(filters.FilterSet):
    # One service area per request, so the M2M join cannot duplicate rows.
    service_area = filters.ModelChoiceFilter(
        field_name="service_areas", queryset=ServiceArea.objects.all()
    )
    search = filters.CharFilter(field_name="business_name", lookup_expr="icontains")

    class Meta:
        model = VendorProfile
        fields = ("offers_food", "offers_drinks")
