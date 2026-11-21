"""Ce qu'OpenStreetMap dit d'un lieu, en français (ADR 0244) : les attributs gardés dans l'index (``KEPT``), les filtres
qu'on y reconnaît (``FEATURES`` : terrasse, végétarien…, rangés en bits pour filtrer vite), la cuisine, l'adresse, le
téléphone, le site, et la fiche en paires libellé/valeur. Pur : ni fichier, ni réseau.

Tout vient de contributeurs : un texte est borné et mis sur une ligne, un site n'est gardé que s'il est en http(s)."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from urllib.parse import urlsplit

from mika.ports.maps import FEATURES

#: les clés gardées pour la fiche (dans l'index, en JSON) ; le nom, la sorte, la position ont leurs colonnes
KEPT = ("cuisine", "opening_hours", "phone", "contact:phone", "mobile", "contact:mobile", "website", "contact:website",
        "url", "email", "contact:email", "outdoor_seating", "diet:vegetarian", "diet:vegan", "wheelchair", "takeaway",
        "delivery", "reservation", "internet_access", "stars", "brand", "operator", "description", "ele",
        "addr:housenumber", "addr:street", "addr:place", "addr:postcode", "addr:city", "wikidata", "wikipedia")
VALUE_MAX = 300
HOURS_MAX = 255

#: chaque filtre reconnu : son bit, la clé qui le dit et les valeurs qui le valent
FEATURE_RULES: dict[str, tuple[int, str, frozenset[str]]] = {
    "terrasse": (1, "outdoor_seating", frozenset({"yes"})),
    "vegetarien": (2, "diet:vegetarian", frozenset({"yes", "only", "limited"})),
    "vegan": (4, "diet:vegan", frozenset({"yes", "only", "limited"})),
    "accessible": (8, "wheelchair", frozenset({"yes", "designated"})),
    "emporter": (16, "takeaway", frozenset({"yes", "only"})),
    "livraison": (32, "delivery", frozenset({"yes", "only"})),
}
assert tuple(FEATURE_RULES) == FEATURES, "les filtres du port, dans son ordre"

#: les cuisines les plus courantes en France, au féminin (« cuisine italienne ») ou telles qu'on les dit
CUISINE_FR = {
    "french": "française", "regional": "régionale", "italian": "italienne", "pizza": "pizza", "burger": "burgers",
    "kebab": "kebab", "sandwich": "sandwichs", "japanese": "japonaise", "sushi": "sushis", "chinese": "chinoise",
    "asian": "asiatique", "vietnamese": "vietnamienne", "thai": "thaïe", "indian": "indienne",
    "lebanese": "libanaise", "moroccan": "marocaine", "mediterranean": "méditerranéenne", "greek": "grecque",
    "turkish": "turque", "spanish": "espagnole", "portuguese": "portugaise", "mexican": "mexicaine",
    "american": "américaine", "korean": "coréenne", "african": "africaine", "belgian": "belge",
    "crepe": "crêpes", "galette": "galettes", "seafood": "fruits de mer", "fish": "poisson",
    "fish_and_chips": "fish and chips", "steak_house": "grillades", "grill": "grillades", "barbecue": "barbecue",
    "chicken": "poulet", "tacos": "tacos", "bagel": "bagels", "breakfast": "petit-déjeuner", "brunch": "brunch",
    "coffee_shop": "café", "tea": "thé", "cake": "gâteaux", "ice_cream": "glaces", "bubble_tea": "bubble tea",
    "vegetarian": "végétarienne", "vegan": "vegane", "international": "internationale", "fine_dining": "gastronomique",
    "savoyard": "savoyarde", "alsatian": "alsacienne", "flemish": "flamande", "basque": "basque",
    "provencal": "provençale", "lyonnaise": "lyonnaise", "couscous": "couscous", "tapas": "tapas",
    "brasserie": "brasserie", "bistro": "bistrot", "wine_bar": "bar à vin", "beer": "bière", "friture": "friterie",
    "fries": "frites", "hot_dog": "hot-dogs", "noodle": "nouilles", "ramen": "ramen", "dumpling": "raviolis",
    "poke": "poké", "salad": "salades", "soup": "soupes", "donut": "beignets", "waffle": "gaufres",
}
_BY_FRENCH = {unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode().casefold(): k
              for k, v in CUISINE_FR.items()}
CUISINES_MAX = 5

YES_NO = {"yes": "oui", "no": "non", "only": "uniquement"}
DIET = {"yes": "oui", "only": "uniquement", "limited": "quelques plats", "no": "non"}
WHEELCHAIR = {"yes": "accessible", "designated": "accessible", "limited": "en partie", "no": "non accessible"}
RESERVATION = {"yes": "possible", "required": "obligatoire", "recommended": "conseillée", "no": "non",
               "only": "obligatoire"}
INTERNET = {"wlan": "Wi-Fi", "yes": "oui", "no": "non", "wired": "par câble", "terminal": "un poste"}


def clean(value: object, most: int = VALUE_MAX) -> str:
    """Une valeur telle qu'on la garde : sur une ligne, sans caractère invisible, bornée."""
    flat = " ".join(str(value).split())
    if not flat.isprintable():
        flat = "".join(ch for ch in flat if ch.isprintable())
    return flat[:most]


def kept(tags: Mapping[str, str]) -> str:
    """Les attributs gardés, en JSON compact ; vide s'il n'y en a aucun."""
    found = {k: clean(tags[k]) for k in KEPT if k in tags and clean(tags[k])}
    return json.dumps(found, ensure_ascii=False, separators=(",", ":")) if found else ""


def read_kept(text: str) -> dict[str, str]:
    """L'inverse de ``kept`` ; un texte illisible ne donne rien."""
    if not text:
        return {}
    try:
        got = json.loads(text)
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}


def features_of(tags: Mapping[str, str]) -> int:
    """Les filtres que ces attributs vérifient (des bits) ; ce qui est vegan est végétarien aussi (OpenStreetMap ne tague
    souvent qu'un ``diet:vegan=only``), sauf un ``diet:vegetarian=no`` explicite."""
    mask = 0
    for bit, key, values in FEATURE_RULES.values():
        if str(tags.get(key, "")).strip().lower() in values:
            mask |= bit
    vegetarian, vegan = FEATURE_RULES["vegetarien"][0], FEATURE_RULES["vegan"][0]
    if mask & vegan and str(tags.get("diet:vegetarian", "")).strip().lower() != "no":
        mask |= vegetarian
    return mask


def features_named(mask: int) -> tuple[str, ...]:
    return tuple(name for name, (bit, _key, _values) in FEATURE_RULES.items() if mask & bit)


def mask_of(names: frozenset[str] | set[str] | tuple[str, ...]) -> int:
    """Le masque de ces filtres ; un filtre inconnu lève ``ValueError`` (le port le refuse)."""
    mask = 0
    for name in names:
        if name not in FEATURE_RULES:
            raise ValueError(f"un filtre inconnu : {name} ({', '.join(FEATURES)})")
        mask |= FEATURE_RULES[name][0]
    return mask


def cuisine_of(tags: Mapping[str, str]) -> str:
    """La cuisine rangée : ses valeurs (« french;regional »), en minuscules, au plus ``CUISINES_MAX``."""
    raw = str(tags.get("cuisine", ""))
    values = []
    for part in raw.replace(",", ";").split(";"):
        value = "_".join(clean(part, 40).lower().split())
        if value and value not in values:
            values.append(value)
    return ";".join(values[:CUISINES_MAX])


def cuisine_label(value: str) -> str:
    return CUISINE_FR.get(value, value.replace("_", " "))


def cuisine_fr(stored: str) -> str:
    """« Flamande, régionale » : la cuisine rangée, en mots."""
    labels = [cuisine_label(v) for v in stored.split(";") if v]
    text = ", ".join(labels)
    return text[:1].upper() + text[1:]


def cuisine_key(asked: str) -> str:
    """La valeur cherchée : une clé d'OpenStreetMap (« italian ») ou son nom en français (« italienne »)."""
    plain = unicodedata.normalize("NFKD", " ".join(asked.split())).encode("ascii", "ignore").decode().casefold()
    if plain in _BY_FRENCH:
        return _BY_FRENCH[plain]
    return "_".join(asked.strip().lower().split())


def address(tags: Mapping[str, str]) -> str:
    """« 12 Rue de la Monnaie, 59800 Lille »."""
    street = tags.get("addr:street") or tags.get("addr:place") or ""
    first = " ".join(p for p in (tags.get("addr:housenumber", ""), street) if p)
    second = " ".join(p for p in (tags.get("addr:postcode", ""), tags.get("addr:city", "")) if p)
    return clean(", ".join(p for p in (first, second) if p))


def phone(tags: Mapping[str, str]) -> str:
    """Le premier numéro ; un numéro français en dix chiffres groupés par deux (« 03 20 06 46 25 »)."""
    for key in ("phone", "contact:phone", "mobile", "contact:mobile"):
        value = clean(tags.get(key, "")).split(";")[0].strip()
        if not value:
            continue
        digits = "".join(ch for ch in value if ch.isdigit() or ch == "+")
        if digits.startswith("+33") and len(digits) == 12:
            digits = "0" + digits[3:]
        if digits.startswith("0033") and len(digits) == 13:
            digits = "0" + digits[4:]
        if len(digits) == 10 and digits.startswith("0") and digits.isdigit():
            return " ".join(digits[i:i + 2] for i in range(0, 10, 2))
        return value[:40]
    return ""


def email(tags: Mapping[str, str]) -> str:
    for key in ("email", "contact:email"):
        value = clean(tags.get(key, "")).split(";")[0].strip()
        if "@" in value and " " not in value:
            return value[:120]
    return ""


def website(tags: Mapping[str, str]) -> str:
    """Le site, en http(s) ; une adresse sans schéma (« www.exemple.fr ») reçoit https ; tout autre schéma : rien."""
    for key in ("website", "contact:website", "url"):
        value = clean(tags.get(key, "")).split(";")[0].strip()
        if not value or " " in value:
            continue
        if "://" not in value:
            value = "https://" + value
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.hostname and "." in parts.hostname:
            return value[:VALUE_MAX]
    return ""


def wikipedia_url(value: str) -> str:
    """« fr:Musée de l'Hospice Comtesse » → l'adresse de l'article."""
    lang, sep, title = clean(value).partition(":")
    if not sep or not lang.isalpha() or len(lang) > 12 or not title.strip():
        return ""
    return f"https://{lang.lower()}.wikipedia.org/wiki/{title.strip().replace(' ', '_')}"


def _stars(value: str) -> str:
    text = value.strip()
    superior = text.upper().endswith("S")
    count = text[:-1] if superior else text
    if not count.isdigit() or not 1 <= int(count) <= 7:
        return ""
    return f"{count} étoile{'s' if int(count) > 1 else ''}{' supérieur' if superior else ''}"


def facts(tags: Mapping[str, str], hours_text: str = "") -> tuple[tuple[str, str], ...]:
    """La fiche, en paires (libellé, valeur), dans l'ordre où on les lit ; seulement ce qui est renseigné."""
    out: list[tuple[str, str]] = []

    def say(label: str, value: str) -> None:
        if value:
            out.append((label, value))

    cuisine = cuisine_of(tags)
    say("Cuisine", cuisine_fr(cuisine).lower() if cuisine else "")
    say("Horaires", hours_text)
    say("Adresse", address(tags))
    say("Téléphone", phone(tags))
    say("Site", website(tags))
    say("Courriel", email(tags))
    say("Terrasse", YES_NO.get(str(tags.get("outdoor_seating", "")).lower(), ""))
    say("Végétarien", DIET.get(str(tags.get("diet:vegetarian", "")).lower(), ""))
    say("Vegan", DIET.get(str(tags.get("diet:vegan", "")).lower(), ""))
    say("Fauteuil roulant", WHEELCHAIR.get(str(tags.get("wheelchair", "")).lower(), ""))
    say("À emporter", YES_NO.get(str(tags.get("takeaway", "")).lower(), ""))
    say("Livraison", YES_NO.get(str(tags.get("delivery", "")).lower(), ""))
    say("Réservation", RESERVATION.get(str(tags.get("reservation", "")).lower(), ""))
    say("Internet", INTERNET.get(str(tags.get("internet_access", "")).lower(), ""))
    say("Classement", _stars(str(tags.get("stars", ""))))
    ele = clean(tags.get("ele", ""), 12).replace(",", ".").removesuffix(" m").removesuffix("m").strip()
    try:
        say("Altitude", f"{round(float(ele)):,} m".replace(",", " ") if ele else "")
    except ValueError:
        pass
    say("Enseigne", clean(tags.get("brand", ""), 120))
    say("Exploitant", clean(tags.get("operator", ""), 120))
    say("Description", clean(tags.get("description", "")))
    return tuple(out)
