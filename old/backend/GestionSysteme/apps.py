from django.apps import AppConfig


class GestionSystemeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "GestionSysteme"
    # Étiquette explicite en minuscules : c'est elle qui sert de préfixe
    # d'espace de noms d'URL et de clé dans ``apps.get_app_config``. La
    # laisser dériver du nom de paquet donnerait une étiquette capitalisée,
    # inhabituelle et facile à mal orthographier dans un ``{% url %}``.
    label = "gestionsysteme"
    verbose_name = "Gestion Système"
