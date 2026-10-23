"""命名 profile 公开契约."""

from app.media.metadata.naming import (
    NamingField,
    NamingProfile,
    list_naming_profiles,
    naming_field_catalog,
    naming_field_keys,
    register_naming_profile,
    render_naming_fields,
)

__all__ = [
    "NamingField",
    "NamingProfile",
    "list_naming_profiles",
    "naming_field_catalog",
    "naming_field_keys",
    "register_naming_profile",
    "render_naming_fields",
]
