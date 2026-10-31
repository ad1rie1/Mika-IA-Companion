/**
 * Le sélecteur d'emojis du champ — la part pure : les familles proposées,
 * l'insertion au curseur, les récents retenus par l'appareil. Le panneau
 * lui-même est dans `EmojiPicker.ts`.
 *
 * Une liste choisie, pas tout Unicode : ce qui se dit dans un chat, rangé
 * par famille. Chaque famille s'écrit en une chaîne séparée par des espaces,
 * pour ne jamais couper un emoji composé (`❤️‍🔥`, `😮‍💨`) en morceaux.
 */

export interface EmojiGroup {
  /** L'onglet : un emoji qui représente la famille. */
  readonly icon: string;
  readonly label: string;
  readonly emojis: readonly string[];
}

function group(icon: string, label: string, list: string): EmojiGroup {
  return { icon, label, emojis: list.trim().split(/\s+/) };
}

export const EMOJI_GROUPS: readonly EmojiGroup[] = [
  group("😀", "Visages", `
    😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😗 😚 😙 🥲 😋 😛 😜 🤪 😝
    🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😮‍💨 😌 😔 😪 🤤 😴 😷 🤒 🤕 🤢 🥵 🥶 🥴
    😵‍💫 🤯 🤠 🥳 😎 🤓 🧐 😕 😟 🙁 😮 😯 😲 😳 🥺 🥹 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣
    😞 😓 😩 😫 🥱 😤 😡 😠 🤬 😈 💀 👻 👽 🤖 💩 🫠 🫡 🫣 🫢 🤡
  `),
  group("👋", "Gestes", `
    👋 🤚 🖐️ ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏
    🙌 🫶 👐 🤲 🤝 🙏 ✍️ 💪 🫂 🙋 🤷 🤦 🙇 💁 🙅 🙆
  `),
  group("❤️", "Cœurs", `
    ❤️ 🧡 💛 💚 💙 💜 🤎 🖤 🤍 🩷 🩵 💔 ❤️‍🔥 ❤️‍🩹 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 💋 💌 😻
  `),
  group("🌸", "Nature", `
    🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🐦 🦉 🦄 🐝 🦋 🐌 🐢 🐙 🐬
    🐳 🐾 🌸 🌹 🌻 🌷 🌼 🌱 🌿 🍀 🍁 🍂 🌳 🌵 🌈 ☀️ 🌤️ ⛅ 🌧️ ⛈️ ❄️ ☃️ 🔥 💧 🌊 🌙
    ⭐ 🌟 🌍
  `),
  group("🍕", "À table", `
    🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🥑 🥕 🌽 🥐 🥖 🧀 🥚 🍳 🥞 🥓 🍔
    🍟 🍕 🌭 🥪 🌮 🍝 🍜 🍣 🍱 🍙 🍰 🎂 🧁 🍩 🍪 🍫 🍬 🍿 ☕ 🍵 🧋 🍺 🍷 🥂 🍾
  `),
  group("⚽", "Loisirs", `
    ⚽ 🏀 🏈 ⚾ 🎾 🏐 🏉 🎱 🏓 🏸 ⛳ 🎣 🚴 🏊 🧘 🎮 🕹️ 🎲 ♟️ 🎯 🎳 🎨 🎭 🎬 🎤 🎧
    🎵 🎶 🎹 🎸 🥁 📚 🎉 🎊 🎁 🎈 🏆 🥇
  `),
  group("💡", "Objets", `
    💡 📱 💻 ⌨️ 🖥️ 🖨️ 📷 📖 ✏️ 📝 📌 📎 ✂️ 🗓️ ⏰ ⌛ 🔑 🔒 🔓 🛠️ ⚙️ 🧪 🔭 💊 🛏️ 🛋️
    🚗 🚆 ✈️ 🚀 🏠 🏖️ ⛰️ 🗺️ 💰 💳 ✉️ 📦 🧸 🕯️
  `),
  group("✨", "Symboles", `
    ✨ ⚡ 💥 💫 💤 💬 💭 ❗ ❓ ‼️ ⁉️ ✅ ❌ ⭕ 🚫 ⚠️ 💯 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ ➡️
    ⬅️ ⬆️ ⬇️ 🔄 ➕ ➖ ✖️ ➗ ♾️ 🆗 🆕 🆒 🔝
  `),
];

/** Tout ce que le panneau propose : un récent hors de la liste n'est pas gardé. */
const KNOWN = new Set(EMOJI_GROUPS.flatMap((g) => g.emojis));

/** Combien de récents l'appareil retient (trois lignes du panneau). */
export const MAX_RECENT = 24;

/**
 * Les récents tels que l'appareil les a gardés — une liste vide pour tout ce
 * qui n'en est pas une : rien de stocké, du JSON cassé, un emoji inconnu
 * (écarté), un doublon (le premier compte).
 */
export function parseRecent(raw: string | null): string[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const recent: string[] = [];
  for (const item of parsed) {
    if (typeof item !== "string" || !KNOWN.has(item) || recent.includes(item)) continue;
    recent.push(item);
    if (recent.length >= MAX_RECENT) break;
  }
  return recent;
}

/** Le dernier choisi en tête, sans doublon, `MAX_RECENT` au plus. */
export function withRecent(recent: readonly string[], emoji: string): string[] {
  return [emoji, ...recent.filter((e) => e !== emoji)].slice(0, MAX_RECENT);
}

/**
 * L'emoji posé au curseur, à la place de la sélection : la nouvelle valeur
 * et la position du curseur juste après. `null` si le champ dépasserait sa
 * limite — le champ la compte en unités UTF-16 (`maxLength`), comme ici.
 */
export function insertEmoji(
  value: string,
  start: number,
  end: number,
  emoji: string,
  maxLength: number,
): { value: string; caret: number } | null {
  const from = Math.max(0, Math.min(start, end, value.length));
  const to = Math.min(value.length, Math.max(start, end, from));
  const next = value.slice(0, from) + emoji + value.slice(to);
  if (next.length > maxLength) return null;
  return { value: next, caret: from + emoji.length };
}
