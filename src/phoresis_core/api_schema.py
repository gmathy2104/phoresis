"""DRF Spectacular schema view for Phoresis APIs."""

from drf_spectacular.views import SpectacularAPIView


class PhoresisSchemaView(SpectacularAPIView):
    """Schema view with Phoresis branding and per-app subset support."""

    schema = None  # falls back to default introspection
