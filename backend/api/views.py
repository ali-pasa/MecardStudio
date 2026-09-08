from django.http import JsonResponse


def health_check(request):
    """Simple health-check endpoint to verify the API is up."""
    return JsonResponse({'status': 'ok', 'service': 'MecardStudio API'})
