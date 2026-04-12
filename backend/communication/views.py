from django.http import JsonResponse

from config.personality import personality


def health(request):
    return JsonResponse({"status": "ok", "vtuber": personality.name})


def get_personality(request):
    return JsonResponse({
        "name": personality.name,
        "description": personality.description,
        "greeting": personality.greeting,
    })
