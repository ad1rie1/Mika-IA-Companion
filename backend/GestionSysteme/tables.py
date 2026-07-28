"""Pagination, tri et filtres — la part réellement commune des tableaux.

Découpage volontaire : **la mécanique est partagée, le balisage des cellules
ne l'est pas.**

Un moteur générique qui rendrait aussi les cellules obligerait chaque page à
décrire ses colonnes dans un mini-langage — et la première colonne un peu
particulière (une pastille d'émotion, une jauge, un lien vers une fiche) le
ferait déborder. L'ancienne interface avait le défaut inverse : 27 vues
réimplémentaient chacune leur en-tête, leur corps *et* leur pagination, soit
35 ``<table>`` bricolés à la main.

Donc ici : le calcul de page, la conservation des paramètres d'URL et la
lecture des filtres sont mutualisés ; le ``<tbody>`` reste dans le gabarit de
la page, où il est lisible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from django.core.paginator import EmptyPage, Paginator

DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 200
PER_PAGE_CHOICES = (25, 50, 100, 200)


@dataclass(frozen=True)
class SortOption:
    """Une colonne triable : libellé de tri → expression ORM."""
    key: str
    label: str
    order_by: tuple[str, ...]


@dataclass
class PageResult:
    """Ce qu'un gabarit doit savoir pour afficher une page de résultats."""
    rows: list[Any]
    total: int
    number: int
    per_page: int
    num_pages: int
    param: str = "page"

    @property
    def has_prev(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.num_pages

    @property
    def prev_number(self) -> int:
        return max(1, self.number - 1)

    @property
    def next_number(self) -> int:
        return min(self.num_pages, self.number + 1)

    @property
    def start_index(self) -> int:
        return 0 if not self.total else (self.number - 1) * self.per_page + 1

    @property
    def end_index(self) -> int:
        return min(self.total, self.number * self.per_page)

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def page_links(self) -> list[int | None]:
        """Numéros de page à afficher, ``None`` marquant une ellipse.

        Toujours : la première, la dernière, et une fenêtre autour de la
        courante. Une liste de 400 pages ne peut pas s'afficher en entier, et
        « page 1 » doit rester à un clic depuis la page 37.
        """
        return _elided_range(self.number, self.num_pages)


def _elided_range(current: int, last: int, *, edge: int = 1, around: int = 2) -> list[int | None]:
    if last <= 1:
        return []
    keep: set[int] = set()
    for n in range(1, edge + 1):
        keep.add(n)
        keep.add(last - n + 1)
    for n in range(current - around, current + around + 1):
        keep.add(n)
    ordered = sorted(n for n in keep if 1 <= n <= last)

    out: list[int | None] = []
    previous = 0
    for n in ordered:
        if previous and n - previous > 1:
            out.append(None)
        out.append(n)
        previous = n
    return out


def read_per_page(request, *, default: int = DEFAULT_PER_PAGE, param: str = "per_page") -> int:
    try:
        value = int(request.GET.get(param, default))
    except (TypeError, ValueError):
        return default
    return max(5, min(MAX_PER_PAGE, value))


def read_page(request, *, param: str = "page") -> int:
    try:
        return max(1, int(request.GET.get(param, 1)))
    except (TypeError, ValueError):
        return 1


def paginate(
    request,
    queryset,
    *,
    per_page: int | None = None,
    default_per_page: int = DEFAULT_PER_PAGE,
    page_param: str = "page",
    per_page_param: str = "per_page",
) -> PageResult:
    """Découpe un queryset (ou une liste) en une page.

    Accepte aussi une séquence en mémoire : plusieurs vues portent sur des
    états vivants en RAM (humeurs par personne, drives, outils MCP) qui n'ont
    pas de queryset derrière eux, et méritent la même pagination.

    Un numéro de page hors bornes retombe sur la dernière page réelle plutôt
    que de lever une 404 : après suppression de lignes, un favori pointant
    « page 12 » doit afficher quelque chose d'utile.
    """
    size = per_page if per_page is not None else read_per_page(
        request, default=default_per_page, param=per_page_param,
    )
    number = read_page(request, param=page_param)

    paginator = Paginator(queryset, size)
    try:
        page = paginator.page(number)
    except EmptyPage:
        number = paginator.num_pages
        page = paginator.page(number)

    return PageResult(
        rows=list(page.object_list),
        total=paginator.count,
        number=page.number,
        per_page=size,
        num_pages=paginator.num_pages,
        param=page_param,
    )


# ── Filtres ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass
class Filter:
    """Un filtre de liste, tel que le gabarit doit l'afficher.

    ``value`` porte la valeur retenue après validation — le gabarit n'a plus
    qu'à la réafficher dans le champ, ce qui garde le formulaire cohérent
    avec les résultats montrés.
    """
    param: str
    label: str
    kind: str = "select"          # select | search
    choices: tuple[Choice, ...] = ()
    value: str = ""
    placeholder: str = ""
    autosubmit: bool = True


def read_choice(request, param: str, allowed: Iterable[str], *, default: str = "") -> str:
    """Lit un paramètre contraint à une liste fermée.

    Une valeur hors liste est ignorée, jamais transmise à l'ORM : c'est ce
    qui empêche un ``?order=`` bricolé de devenir un tri arbitraire — voire
    une fuite via une relation traversée.
    """
    raw = (request.GET.get(param) or "").strip()
    return raw if raw in set(allowed) else default


def read_text(request, param: str, *, max_length: int = 120) -> str:
    """Lit un champ de recherche libre, borné en longueur."""
    return (request.GET.get(param) or "").strip()[:max_length]


def select_filter(
    request,
    param: str,
    label: str,
    choices: Sequence[tuple[str, str]],
    *,
    default: str = "",
    all_label: str = "Tous",
) -> Filter:
    """Construit un filtre à choix + lit sa valeur courante en une fois."""
    opts = (Choice("", all_label),) + tuple(Choice(v, l) for v, l in choices)
    value = read_choice(request, param, [c.value for c in opts if c.value], default=default)
    return Filter(param=param, label=label, kind="select", choices=opts, value=value)


def search_filter(
    request, param: str = "q", label: str = "Recherche", *, placeholder: str = "",
) -> Filter:
    return Filter(
        param=param, label=label, kind="search",
        value=read_text(request, param), placeholder=placeholder,
        autosubmit=False,
    )


@dataclass
class FilterSet:
    """Regroupe les filtres d'une liste pour un rendu en une inclusion."""
    filters: list[Filter] = field(default_factory=list)
    per_page: int = DEFAULT_PER_PAGE
    show_per_page: bool = True

    def add(self, f: Filter) -> Filter:
        self.filters.append(f)
        return f

    @property
    def active(self) -> bool:
        return any(f.value for f in self.filters)

    @property
    def per_page_choices(self) -> tuple[int, ...]:
        return PER_PAGE_CHOICES
