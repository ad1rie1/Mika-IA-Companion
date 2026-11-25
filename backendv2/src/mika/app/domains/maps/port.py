"""Leur part du port d'entrée (ADR 0119, 0310) : la position que donne le téléphone d'une personne, et son retrait
(``locate``, ``unlocate`` : sa session de chat, ``adapters/web/chat_session.py``), puis la case de la carte qui se
précharge ; les petites bulles de ce qu'elle a fait en écrivant ses messages (``notes`` : la position regardée, un
lieu cherché ou montré, un voyage — le fil du chat, ``adapters/web/hub.py``). ``app/mindport.py::KernelPort`` mêle
leurs méthodes aux siennes."""

from __future__ import annotations

from collections.abc import Sequence

from mika.app.domains.domain import PortPart
from mika.contracts import identity as identity_c
from mika.contracts import location as location_c
from mika.contracts import trips as trips_c
from mika.contracts.entry import MessageNote
from mika.kernel.events import Content, Origin
from mika.plugins import location
from mika.runtime.effects import with_content
from mika.vocab.privacy import Sensitivity


class MapsPort:
    """La position d'une personne et les bulles de ses messages. Elles lisent ``self.kernel`` et ``self._store``, que
    pose ``KernelPort``."""

    # ── où est la personne, d'après son téléphone (ADR 0119) ──
    async def locate(self, handle: str, *, lat: float, lon: float, accuracy_m: int, label: str,
                     age_ms: int) -> int | None:
        """Une position, à son adresse et à sa personne pour sujets ; coordonnées et lieu sont personnels (l'oubli
        de la personne les efface). Puis les avis de sa case se préchargent (ADR 0259 : le port de la carte met en file
        la case et ses voisines, lues en fond ; seules les cases partent, jamais la position) — sans retenir la
        réponse."""
        mind = self.kernel.mind
        person = mind.frame().get(identity_c.PERSON(handle)) or handle
        level = int(Sensitivity.PERSONAL)
        draft = location_c.LOCATED.draft(
            handle=handle, person=person, coords=Content.of(f"{lat:.6f},{lon:.6f}", level=level),
            label=Content.of(label, level=level) if label else None, accuracy_m=max(0, int(accuracy_m)),
            fixed_at=mind.clock.now() - max(0, int(age_ms)) * 1000)
        commit = await mind.append([draft], emitter=location_c.OWNER, correlation=f"lieu:{handle}",
                                   origin=Origin.EXTERNAL)
        maps = self.kernel.ports.get("maps")
        if maps is not None and commit.seqs and hasattr(maps, "preload"):
            maps.preload(lat, lon)
        return commit.seqs[-1] if commit.seqs else None

    async def unlocate(self, handle: str) -> int | None:
        mind = self.kernel.mind
        frame = mind.frame()
        if not location.known(frame.root.slices.get(location_c.OWNER), handle):
            return None
        draft = location_c.CLEARED.draft(handle=handle, person=frame.get(identity_c.PERSON(handle)) or handle)
        commit = await mind.append([draft], emitter=location_c.OWNER, correlation=f"lieu:{handle}",
                                   origin=Origin.EXTERNAL)
        return commit.seqs[-1] if commit.seqs else None

    def notes(self, ids: Sequence[str]) -> list[MessageNote]:
        """Les petites bulles de ce qu'elle a fait en écrivant ses messages, relues au journal : la position qu'elle a
        regardée (le lieu, sinon les coordonnées), ce qu'elle a cherché sur la carte (``look:``) ou montré
        (``map:``), le voyage qu'elle a créé ou changé (``trip:``, son titre d'aujourd'hui). Vides une fois oubliés,
        ou le voyage supprimé — et rien à ouvrir (``ref`` vide)."""
        located = {seq: ref for ref in ids if (seq := location_c.note_seq(ref)) is not None}
        marked = {ref: got for ref in ids if (got := trips_c.note_of(ref)) is not None}
        seen = {int(ident): (kind, ref) for ref, (kind, ident) in marked.items() if kind != trips_c.NOTE_TRIP}
        mind = self.kernel.mind
        found: dict[str, MessageNote] = {}
        looked = {trips_c.NOTE_LOOK: (trips_c.LOOKED.name, "query"), trips_c.NOTE_MAP: (trips_c.SHOWN.name, "title")}
        for stored in mind.store.get_events([*located, *seen]) if located or seen else ():
            ev = mind.decode(stored)
            if ev.type.name == location_c.LOCATED.name and ev.seq in located:
                d = with_content(mind, ev).data
                text = (d.label.text if d.label is not None else None) or d.coords.text or ""
                found[located[ev.seq]] = MessageNote(id=located[ev.seq], kind=location_c.NOTE_KIND, text=text,
                                                     at=d.fixed_at // 1000)
            elif ev.seq in seen and looked[seen[ev.seq][0]][0] == ev.type.name:
                kind, ref = seen[ev.seq]
                said = getattr(with_content(mind, ev).data, looked[kind][1]).text  # None : oublié
                found[ref] = MessageNote(id=ref, kind=kind, text=said or "", at=ev.at // 1000,
                                         ref=str(ev.seq) if said is not None else "")
        state = mind.frame().state(trips_c.OWNER) if any(k == trips_c.NOTE_TRIP for k, _ in marked.values()) else None
        for ref, (kind, ident) in marked.items():
            if kind != trips_c.NOTE_TRIP:
                continue
            trip = state.trips.get(ident) if state is not None else None
            title = self._store.content([trip.title_ref]).get(trip.title_ref) if trip is not None else None
            found[ref] = MessageNote(id=ref, kind=kind, text=title or "", at=trip.updated_at // 1000 if trip else 0,
                                     ref=trip.id if trip is not None and title is not None else "")
        return [found[ref] for ref in ids if ref in found]


PORT = PortPart(methods=MapsPort)
