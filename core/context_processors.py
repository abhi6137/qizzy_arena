from datetime import datetime


def global_settings(request):
    return {
        "APP_NAME": "Quizy+",
        "CURRENT_YEAR": datetime.utcnow().year,
    }
