/*
 * Couper un texte sans le casser, et reconnaître la version d'un message. Pur : chargé dans la page Teams, dans le
 * relais, dans le service d'arrière-plan, dans la page de réglages, et par les tests sous Node.
 *
 * Une chaîne JavaScript compte en unités UTF-16 : un emoji en prend deux (une paire de substitution). Un `slice` qui
 * tombe entre les deux laisse une moitié seule, que le serveur refuse — et avec elle tout le lot. Toute coupe passe
 * donc par `cut` (ou `clip`, qui ajoute « … »).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module && module.exports) module.exports = api;
  else root.MikaTeamsText = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

  /** La chaîne bien formée : une moitié de paire seule devient U+FFFD (même longueur). */
  function wellFormed(s) {
    const t = typeof s === "string" ? s : s === undefined || s === null ? "" : String(s);
    return typeof t.toWellFormed === "function" ? t.toWellFormed() : t.replace(LONE_SURROGATE, "�");
  }

  /** Au plus `max` unités UTF-16, bien formée, jamais coupée au milieu d'une paire de substitution. */
  function cut(s, max) {
    const t = wellFormed(s);
    if (!(max >= 0) || t.length <= max) return t;
    let end = Math.floor(max);
    const c = t.charCodeAt(end - 1);
    if (c >= 0xd800 && c <= 0xdbff) end--; // bien formée : la moitié basse suit, elle partirait seule
    return t.slice(0, end);
  }

  /** Comme `cut`, mais une chaîne raccourcie finit par « … » (compris dans `max`). */
  function clip(s, max) {
    const t = wellFormed(s);
    if (!(max >= 0) || t.length <= max) return t;
    if (max < 1) return "";
    return cut(t, max - 1).trimEnd() + "…";
  }

  /** Un petit condensé stable (djb2, en base 36). */
  function hash(s) {
    const t = String(s || "");
    let h = 5381;
    for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  /** La marque d'un message supprimé : une fois vue, aucune version de son texte ne repart. */
  function deletedKey(id) {
    return String(id) + "#×";
  }

  /**
   * Ce que disent les réactions d'un message (ADR 0300) : « » quand la source ne les dit pas (on n'en sait rien), « 0 »
   * quand elle dit qu'il n'y en a aucune, sinon chaque réaction (sa clé, combien, la sienne, qui).
   */
  function reactionsSignature(m) {
    if (!Array.isArray(m.reactions)) return "";
    if (!m.reactions.length) return "0";
    return m.reactions.map(function (r) {
      return [r.key, r.count, r.mine ? 1 : 0, (r.by || []).join(",")].join(":");
    }).join("|");
  }

  /**
   * La clé d'une version de message : son identifiant, un condensé de son texte et, s'il en a de dites, de ses
   * réactions (ADR 0300). Un message modifié, ou dont les réactions ont changé, garde son identifiant mais change de
   * clé : il repart, et le serveur met le sien à jour. Un message sans réactions dites garde la clé d'avant. (`#` et
   * `~` n'entrent dans aucun identifiant que le serveur accepte.)
   */
  function versionKey(m) {
    if (m.deleted) return deletedKey(m.id);
    const reactions = reactionsSignature(m);
    return String(m.id) + "#" + hash(m.text) + (reactions ? "~" + hash(reactions) : "");
  }

  /**
   * Cette version du message est à faire passer : sa clé n'est pas déjà passée (`sent`, un `Set`), ce n'est pas le
   * texte d'un message déjà vu supprimé, ni une version plus ancienne qu'une déjà vue (`latest`, une `Map`
   * identifiant → version ; comparé seulement quand les deux versions sont connues — un cache en retard ne fait pas
   * revenir un ancien texte). Une clé déjà passée repasse seulement comme une version plus récente que toutes celles
   * vues : une réaction retirée (le message redevient tel qu'il était), un texte remis comme avant. Met `sent` et
   * `latest` à jour quand elle passe.
   */
  function freshVersion(m, sent, latest) {
    const key = versionKey(m);
    const prev = latest.get(m.id);
    const rank = m.deleted ? Infinity : Number(m.version) || 0;
    if (prev === Infinity && !m.deleted) return false;
    if (rank > 0 && prev > 0 && rank < prev) return false;
    if (sent.has(key) && !(rank > 0 && prev > 0 && rank > prev)) return false;
    sent.add(key);
    latest.set(m.id, Math.max(prev || 0, rank));
    return true;
  }

  return { wellFormed: wellFormed, cut: cut, clip: clip, hash: hash, versionKey: versionKey, deletedKey: deletedKey,
    freshVersion: freshVersion, reactionsSignature: reactionsSignature };
});
