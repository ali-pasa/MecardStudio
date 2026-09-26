def get_request_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def request_audit_values(request, *, creating=False):
    actor = request.user if request.user.is_authenticated else None
    values = {
        "updated_by": actor,
        "ip_address": get_request_ip(request),
    }
    if creating:
        values["created_by"] = actor
    return values


def apply_request_audit(instance, request, *, creating=None):
    if creating is None:
        creating = instance._state.adding

    values = request_audit_values(request, creating=creating)
    for field, value in values.items():
        setattr(instance, field, value)
