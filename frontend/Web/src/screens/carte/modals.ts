/**
 * Carte : les fenêtres d'un voyage — « Nouveau voyage » (depuis Voyages, ou « Ajouter au voyage » d'Explorer avec son
 * premier arrêt), « Le voyage » (ce qu'on en change, le supprimer) et « Ajouter un arrêt » à un jour. Elles se posent
 * hors de l'écran (`#modal-root`) ; ce qu'elles écrivent sur le voyage ouvert passe par les gestes de Voyages
 * (`trip.ts`), que le cadre (`index.ts`) leur donne (`ModalsHost`).
 */
import {
  addStop,
  changeTrip,
  createTrip,
  removeTrip,
  searchPlaces,
  CARTE_LIMITS,
  type Place,
  type Trip,
} from "../../api/carte";
import { tripPins } from "../../map/cards";
import { placeWhat } from "../../map/words";
import { h, on } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { confirmModal, failureText, newNonce, toastFailure } from "../../shared/kit";
import { newTripValues, tripChanges, type TripForm } from "./format";
import type { CarteFrame } from "./index";
import { ADDRESS_WAIT_MS, ADDRESSES_SUGGESTED, refused, wantsAddress } from "./requests";
import { tripFormFoot, tripFormMarkup } from "./view";

/** Ce que les fenêtres demandent au cadre, et par lui à Voyages. */
export interface ModalsHost extends CarteFrame {
  /** Le voyage ouvert, sinon "". */
  tripId(): string;
  /** Le voyage ouvert tel qu'on le montre. */
  shownTrip(): Trip | null;
  /** Ajouter un lieu à un voyage (au voyage ouvert, après ses autres gestes). */
  addPlace(trip: string, title: string, p: Place, day: number, index: number, nonce: string, note?: string): Promise<{ ok: boolean; error: unknown }>;
  /** Un geste sur le voyage ouvert, après ceux d'avant. */
  gesture(id: string, write: () => Promise<unknown>, quiet?: boolean): Promise<{ ok: boolean; error: unknown }>;
  /** Un voyage changé : relu, sa miniature et la liste aussi. */
  invalidateTrip(id: string): void;
}

/** Ce qui désigne un lieu, d'une recherche à l'autre (son identifiant d'index change à chaque reconstruction). */
function placeIntent(p: Place): string {
  return `${p.lat},${p.lon},${p.name}`;
}

export class TripModals {
  constructor(private readonly host: ModalsHost) {}

  /** Ce que dit la fenêtre d'un voyage (ses cases, cachées ou non : `newTripValues` et `tripChanges` en décident). */
  private readTripForm(form: HTMLFormElement, mode: string): TripForm {
    const data = new FormData(form);
    return { title: String(data.get("title") ?? ""), start: String(data.get("start") ?? ""), mode: String(data.get("mode") ?? mode),
      avoid: data.getAll("avoid").map(String) };
  }

  /** « En voiture, éviter » suit le mode choisi : ses cases ne se montrent qu'en voiture. */
  private followTripMode(el: HTMLElement): void {
    const mode = el.querySelector<HTMLSelectElement>("[data-trip-mode]");
    const avoid = el.querySelector<HTMLElement>("[data-trip-avoid]");
    mode?.addEventListener("change", () => {
      if (avoid) avoid.hidden = mode.value !== "voiture";
    });
  }

  /** Un voyage neuf : un titre, une date, un mode, ce qu'il évite en voiture ; `first` : son premier arrêt (« Ajouter au voyage »). */
  newTripModal(opts: { first?: Place } = {}): void {
    const el = openModal({
      title: "Nouveau voyage",
      size: "narrow",
      body: tripFormMarkup({ edit: false, title: opts.first ? `Autour de ${opts.first.town || opts.first.name}` : "", start: "", mode: "voiture",
        avoid: [], first: opts.first ?? null }),
      foot: tripFormFoot(false),
    });
    this.followTripMode(el);
    const form = el.querySelector<HTMLFormElement>("[data-trip-form]")!;
    const error = el.querySelector<HTMLElement>("[data-erreur]")!;
    const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
    // les clés de cette fenêtre : « Créer » redit après une panne rend le même voyage, et son premier arrêt une fois
    let nonce = newNonce();
    let firstNonce = newNonce();
    const submit = async () => {
      if (ok.disabled) return;
      const values = newTripValues(this.readTripForm(form, "voiture"));
      if (!values.title) {
        error.innerHTML = `${ico("alert", "xs")}<span>Un voyage a un titre.</span>`;
        error.hidden = false;
        return;
      }
      ok.disabled = true;
      try {
        const made = await createTrip(values, nonce);
        if (opts.first) {
          await addStop(made.id, { name: opts.first.name.slice(0, CARTE_LIMITS.name) || "Lieu", lat: opts.first.lat, lon: opts.first.lon,
            kind: (opts.first.kind_fr || "").slice(0, CARTE_LIMITS.kind), day: 1, index: -1 }, firstNonce);
        }
        closeModal();
        this.host.trips.invalidate();
        toast("Voyage créé.", { ico: "plus" });
        this.host.shell.go(`#carte/voyages/${encodeURIComponent(made.id)}`);
      } catch (err) {
        // refusé (un titre, la borne des voyages) : la prochaine fois est une autre demande
        if (refused(err)) {
          nonce = newNonce();
          firstNonce = newNonce();
        }
        ok.disabled = false;
        error.innerHTML = `${ico("alert", "xs")}<span>${h(failureText(err))}</span>`;
        error.hidden = false;
      }
    };
    ok.addEventListener("click", () => void submit());
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      void submit();
    });
  }

  editTripModal(trip: Trip): void {
    const el = openModal({
      title: "Le voyage",
      size: "narrow",
      body: tripFormMarkup({ edit: true, title: trip.title, start: trip.start, mode: trip.mode, avoid: trip.avoid }),
      foot: tripFormFoot(true),
    });
    this.followTripMode(el);
    const form = el.querySelector<HTMLFormElement>("[data-trip-form]")!;
    const error = el.querySelector<HTMLElement>("[data-erreur]")!;
    const okButton = el.querySelector<HTMLButtonElement>("[data-ok]")!;
    const say = (text: string) => {
      error.innerHTML = `${ico("alert", "xs")}<span>${h(text)}</span>`;
      error.hidden = false;
    };
    let nonce = newNonce();
    okButton.addEventListener("click", async () => {
      if (okButton.disabled) return;
      const said = this.readTripForm(form, trip.mode);
      if (!said.title.trim()) return say("Un voyage a un titre.");
      // ce qui a changé ; ce qu'il évite ne part qu'en voiture (un voyage qui la quitte ne l'envoie plus)
      const values = tripChanges(trip, said);
      if (!Object.keys(values).length) {
        closeModal();
        return;
      }
      okButton.disabled = true;
      // après les autres gestes ; son trajet se relit s'il a changé de mode ou de ce qu'il évite
      const { ok, error: err } = await this.host.gesture(trip.id, () => changeTrip(trip.id, values, nonce), true);
      okButton.disabled = false;
      if (ok) {
        closeModal();
        toast("Voyage modifié.", { ico: "check" });
        return;
      }
      if (refused(err)) nonce = newNonce();
      if (err) say(failureText(err));
    });
    el.querySelector("[data-delete]")?.addEventListener("click", async () => {
      closeModal();
      const yes = await confirmModal({ title: "Supprimer ce voyage ?", text: `« ${trip.title} » et tous ses arrêts disparaissent. Mika ne s'en souviendra plus comme d'un voyage à faire.`, ok: "Supprimer", danger: true });
      if (!yes) return;
      try {
        await removeTrip(trip.id, newNonce());
        this.host.invalidateTrip(trip.id);
        toast("Voyage supprimé.", { ico: "trash" });
        this.host.shell.go("#carte/voyages");
      } catch (err) {
        toastFailure(err);
      }
    });
  }

  /** Ajouter un arrêt à un jour : un lieu de l'index, une adresse, ta position. */
  addStopModal(day: number): void {
    const id = this.host.tripId();
    const trip = this.host.shownTrip();
    if (!id || !trip) return;
    const el = openModal({
      title: `Ajouter un arrêt · jour ${day}`,
      body: `<div class="stack add-stop-modal">
        <label class="search-field">${ico("search", "sm")}<input type="search" data-stop-q maxlength="200" placeholder="Un lieu, une adresse…" aria-label="Chercher un lieu ou une adresse" autocomplete="off"></label>
        <div class="add-stop-list" data-stop-list></div>
        <label class="field"><span>Une note <span class="muted">(facultatif)</span></span><input data-stop-note maxlength="${CARTE_LIMITS.note}" placeholder="Réserver avant le 15, arriver avant 17 h…"></label></div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Fermer</button>`,
    });
    const input = el.querySelector<HTMLInputElement>("[data-stop-q]")!;
    const list = el.querySelector<HTMLElement>("[data-stop-list]")!;
    const noteInput = el.querySelector<HTMLInputElement>("[data-stop-note]")!;
    let found: Place[] = [];
    let message = "";
    let seq = 0;
    let timer = 0;
    let addrTimer = 0;
    let typedAt = 0;
    /** Un lieu qui s'ajoute (les autres attendent) ; la clé de chaque lieu choisi, gardée le temps de la fenêtre. */
    let sending = false;
    const keys = new Map<string, string>();
    const here = this.host.here();
    // chercher près de ce jour du voyage (son dernier arrêt, sinon celui d'avant) ; un voyage vide : près de toi
    const near = (() => {
      const before = trip.days.filter((d) => d.n <= day).flatMap((d) => d.stops)
        .filter((s) => typeof s.lat === "number" && typeof s.lon === "number");
      const last = before[before.length - 1] ?? tripPins(trip)[0];
      return last ? { lat: last.lat as number, lon: last.lon as number } : here;
    })();
    const paintList = () => {
      const off = sending ? " disabled" : "";
      const mine = here && !input.value.trim()
        ? `<button class="li place" type="button" data-stop-here${off}>${ico("pin", "sm")}<span class="li-main"><span class="li-title">Ma position</span><span class="li-snip">${h(here.label || "ta dernière position")}</span></span></button>` : "";
      list.innerHTML = mine + (message ? `<p class="small muted">${h(message)}</p>` : "") + found
        .map((p, i) => `<button class="li place" type="button" data-stop-pick="${i}"${off}>${ico("search", "sm")}<span class="li-main"><span class="li-title">${h(p.name)}</span><span class="li-snip">${h(placeWhat(p))}</span></span></button>`)
        .join("");
    };
    const run = async () => {
      const q = input.value.trim();
      const mine = ++seq;
      window.clearTimeout(addrTimer);
      if (q.length < 2) {
        found = [];
        message = "";
        paintList();
        return;
      }
      let placesError = "";
      const places = await searchPlaces({ q, near, limit: 8 }).catch((err: unknown) => {
        placesError = failureText(err);
        return [] as Place[];
      });
      if (mine !== seq) return;
      // une adresse, si le texte en a l'air : gardée par texte, demandée une fois la saisie arrêtée
      const wanted = !!this.host.carte.value?.addresses.ready && wantsAddress(q);
      const known = wanted ? this.host.addressBook.peek(q) : null;
      found = [...(known ?? []).slice(0, ADDRESSES_SUGGESTED), ...places];
      const waiting = wanted && !known;
      message = placesError || (!found.length && !waiting ? "Rien de tel." : "");
      paintList();
      if (!waiting) return;
      addrTimer = window.setTimeout(async () => {
        let addrError = "";
        const got = await this.host.addressBook.lookup(q).catch((err: unknown) => {
          addrError = `Adresses : ${failureText(err)}`;
          return [] as Place[];
        });
        if (mine !== seq) return;
        found = [...got.slice(0, ADDRESSES_SUGGESTED), ...places];
        message = [placesError, addrError].filter(Boolean).join(" ") || (!found.length ? "Rien de tel." : "");
        paintList();
      }, Math.max(0, typedAt + ADDRESS_WAIT_MS - Date.now()));
    };
    input.addEventListener("input", () => {
      typedAt = Date.now();
      window.clearTimeout(timer);
      window.clearTimeout(addrTimer);
      timer = window.setTimeout(() => void run(), 300);
    });
    const choose = async (p: Place) => {
      if (sending) return;
      // une clé par lieu choisi : un double clic, un réessai après une panne ne l'ajoutent qu'une fois
      const intent = placeIntent(p);
      const nonce = keys.get(intent) ?? newNonce();
      keys.set(intent, nonce);
      sending = true;
      paintList();
      const { ok, error } = await this.host.addPlace(id, trip.title, p, day, -1, nonce, noteInput.value.trim().slice(0, CARTE_LIMITS.note));
      sending = false;
      if (ok) {
        closeModal();
        return;
      }
      if (refused(error)) keys.delete(intent);
      paintList();
    };
    on(list, "[data-stop-pick]", "click", (_e, b) => {
      const p = found[Number(b.dataset.stopPick)];
      if (p) void choose(p);
    });
    on(list, "[data-stop-here]", "click", () => {
      if (here) void choose({ id: "", name: here.label || "Ma position", kind: "", kind_fr: "Ta position", category: "", lat: here.lat, lon: here.lon, town: "", distance_m: null, along_m: null });
    });
    paintList();
  }
}
