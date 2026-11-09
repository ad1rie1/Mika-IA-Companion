/** Lire et écrire le stockage du navigateur sans jamais lever : fermé, on fait sans. */

export function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

export function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // stockage fermé : le choix vaut pour cette page
  }
}
