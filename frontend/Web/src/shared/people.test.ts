import { describe, expect, it } from "vitest";
import { parseAddresses } from "./people";

describe("les adresses", () => {
  it("lit un en-tête : noms, guillemets, virgules dans un nom, adresses seules", () => {
    expect(parseAddresses('Claire Dubois <C.Dubois@lumen.fr>, "Dupré, Élodie" <elodie@exemple.fr>; marc@lumen.fr')).toEqual([
      { name: "Claire Dubois", address: "c.dubois@lumen.fr" },
      { name: "Dupré, Élodie", address: "elodie@exemple.fr" },
      { name: "", address: "marc@lumen.fr" },
    ]);
    expect(parseAddresses("pas une adresse")).toEqual([]);
    expect(parseAddresses("")).toEqual([]);
  });
});
