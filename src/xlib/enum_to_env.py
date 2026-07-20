from django.core.exceptions import ImproperlyConfigured


def enum_to_env(enum_cls, value):
    for x in enum_cls:
        if x.value == value:
            return x
    raise ImproperlyConfigured(
        f"Env value {value!r} could not be found in {enum_cls!r}",
    )