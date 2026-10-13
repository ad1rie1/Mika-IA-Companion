"""Génère les types TypeScript du protocole ``mika.world/1`` depuis le schéma JSON publié par le noyau.

Le jumeau de ``frontend/Unity/tools/gen_world_protocol.py`` (qui écrit le C# d'Unity) : le noyau (``backendv2``)
fait foi, ``mika.adapters.world.protocol.json_schema()`` décrit les trames dans les deux sens et la définition du
monde, et ce script en tire un seul fichier pour le client web. Un champ ajouté côté noyau arrive ici par une
régénération, jamais par une recopie à la main.

    backendv2/.venv/bin/python frontend/Web/tools/gen_world_protocol.py            # écrit le fichier
    backendv2/.venv/bin/python frontend/Web/tools/gen_world_protocol.py --check    # échoue s'il a vieilli

Ce qui est produit (``frontend/Web/src/world/protocol.g.ts``) :

- un type littéral par énumération du schéma (``Posture = "stand" | "sit" | "lie"``) ;
- une interface par objet, aux noms de champs du fil (``to_place``, ``duration_us``) : le client lit le JSON tel
  quel, sans conversion ;
- une union discriminée par union du schéma (``ClientFrame`` par ``type``, ``Location`` par ``kind``…), et la liste
  de ses discriminants (``SERVER_FRAME_TYPES``…) pour reconnaître une trame d'un type inconnu ;
- les débits et les rôles exigés par commande (``RATES``, ``REQUIRES``).

Un champ requis par le schéma est requis ; les autres sont facultatifs (``?``), et ``| null`` quand le schéma
l'admet. Le discriminant d'une union est toujours requis : c'est lui qui fait choisir le membre.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backendv2" / "src"))

OUT = ROOT / "frontend" / "Web" / "src" / "world" / "protocol.g.ts"

# Le nom TypeScript d'une union discriminée, reconnue par l'ensemble de ses membres — les mêmes que côté Unity.
# Une union inconnue est une erreur : on la nomme ici plutôt que de laisser le générateur inventer un nom.
UNIONS: dict[frozenset[str], str] = {
    frozenset({"InRoom", "On", "In", "Held"}): "Location",
    frozenset({"ActorMoved", "ActorBusy", "ObjectMoved", "ObjectSet", "ObjectGone"}): "Change",
    frozenset({"DefPut", "DefRemove"}): "DefChange",
    frozenset({"RoomDef", "PlaceDef", "ArchetypeDef", "ObjectDef", "ActorDef"}): "DefItem",
    frozenset({"Progress", "Finished", "Settled", "NpcUpdate", "Sound", "Loaded"}): "ReportBody",
}


def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s.:/]+", name) if p)


def upper_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def jsdoc(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    lines = [ln.rstrip().replace("*/", "*\\/") for ln in text.strip().splitlines()]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    return [f"{indent}/**"] + [f"{indent} * {ln}".rstrip() for ln in lines] + [f"{indent} */"]


class Gen:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.defs: dict[str, dict[str, Any]] = {}
        for section in ("client", "server", "world"):
            for name, d in schema[section].get("$defs", {}).items():
                if name in self.defs and self.defs[name] != d:
                    raise SystemExit(f"définition {name} différente selon les sections")
                self.defs[name] = d
        self.defs["WorldDef"] = {k: v for k, v in schema["world"].items() if k != "$defs"}
        self.client = schema["client"]
        self.server = schema["server"]
        self.union_of: dict[str, tuple[str, str, str]] = {}  # membre → (union, discriminant, valeur)
        self.unions: dict[str, tuple[str, list[tuple[str, str]]]] = {}  # union → (discriminant, [(valeur, membre)])
        self.inline_enums: dict[str, list[str]] = {}
        self.register_union("ClientFrame", self.client)
        self.register_union("ServerFrame", self.server)
        self.walk_unions()

    # --- unions -------------------------------------------------------------------------------------------
    def register_union(self, name: str, node: dict[str, Any]) -> str:
        disc = node["discriminator"]
        prop = disc["propertyName"]
        members = [(value, ref.split("/")[-1]) for value, ref in sorted(disc["mapping"].items())]
        if name in self.unions:
            if self.unions[name] != (prop, members):
                raise SystemExit(f"union {name} incohérente")
            return name
        self.unions[name] = (prop, members)
        for value, member in members:
            prev = self.union_of.get(member)
            if prev and prev[0] != name:
                raise SystemExit(f"{member} appartient à deux unions : {prev[0]} et {name}")
            self.union_of[member] = (name, prop, value)
        return name

    def union_name(self, node: dict[str, Any]) -> str:
        members = frozenset(ref.split("/")[-1] for ref in node["discriminator"]["mapping"].values())
        name = UNIONS.get(members)
        if name is None:
            raise SystemExit(f"union sans nom : {sorted(members)} — ajoute-la à UNIONS")
        return self.register_union(name, node)

    def walk_unions(self) -> None:
        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if "discriminator" in node and "oneOf" in node and node is not self.client and node is not self.server:
                    self.union_name(node)
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for v in node:
                    visit(v)

        for d in self.defs.values():
            visit(d)

    # --- types --------------------------------------------------------------------------------------------
    def ts_type(self, owner: str, prop: str, node: dict[str, Any]) -> tuple[str, bool]:
        """(type TypeScript, annulable dans le schéma)."""
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            nullable = len(options) < len(node["anyOf"])
            if len(options) != 1:
                raise SystemExit(f"{owner}.{prop} : anyOf non pris en charge")
            t, _ = self.ts_type(owner, prop, options[0])
            return t, nullable
        if "$ref" in node:
            return node["$ref"].split("/")[-1], False
        if "discriminator" in node and "oneOf" in node:
            return self.union_name(node), False
        if "const" in node:
            return json.dumps(node["const"], ensure_ascii=False), False
        if "enum" in node:
            name = owner + pascal(prop)
            self.inline_enums[name] = list(node["enum"])
            return name, False
        t = node.get("type")
        if t == "string":
            return "string", False
        if t in ("integer", "number"):
            return "number", False
        if t == "boolean":
            return "boolean", False
        if t == "array":
            inner, _ = self.ts_type(owner, prop, node.get("items", {}))
            return (f"({inner})[]" if "|" in inner else f"{inner}[]"), False
        if t == "object" and isinstance(node.get("additionalProperties"), dict):
            inner, _ = self.ts_type(owner, prop, node["additionalProperties"])
            return f"Record<string, {inner}>", False
        raise SystemExit(f"{owner}.{prop} : type non pris en charge {node}")

    # --- émission -----------------------------------------------------------------------------------------
    @staticmethod
    def emit_enum(name: str, values: list[str], doc: str | None) -> list[str]:
        out = jsdoc(doc, "")
        out.append(f"export type {name} = {' | '.join(json.dumps(v, ensure_ascii=False) for v in values)};")
        out.append(f"export const {upper_snake(name)}_VALUES: readonly {name}[] = "
                   f"[{', '.join(json.dumps(v, ensure_ascii=False) for v in values)}];")
        return out

    def emit_interface(self, name: str, d: dict[str, Any]) -> list[str]:
        props = d.get("properties", {})
        required = set(d.get("required", []))
        union = self.union_of.get(name)
        out = jsdoc(d.get("description"), "")
        out.append(f"export interface {name} {{")
        for prop, node in props.items():
            out += jsdoc(node.get("description"), "  ")
            if union and prop == union[1]:
                out.append(f"  {prop}: {json.dumps(union[2], ensure_ascii=False)};")
                continue
            t, nullable = self.ts_type(name, prop, node)
            optional = prop not in required
            out.append(f"  {prop}{'?' if optional else ''}: {t}{' | null' if nullable else ''};")
        out.append("}")
        return out

    def emit_union(self, name: str) -> list[str]:
        prop, members = self.unions[name]
        out = [f"/** Union discriminée par « {prop} » : "
               + ", ".join(f"{m} (« {v} »)" for v, m in members) + ". */"]
        out.append(f"export type {name} = {' | '.join(m for _, m in members)};")
        out.append(f"/** Les valeurs de « {prop} » que ce client connaît : une autre est une trame plus récente que lui. */")
        out.append(f"export const {upper_snake(name)}_{prop.upper()}S: readonly {name}[{json.dumps(prop)}][] = "
                   f"[{', '.join(json.dumps(v, ensure_ascii=False) for v, _ in members)}];")
        return out

    def render(self, protocol: str, rates: dict[str, float], requires: dict[str, list[str]]) -> str:
        # Les interfaces d'abord : elles enregistrent les énumérations en ligne au passage.
        interfaces: list[str] = []
        for name in sorted(self.defs):
            d = self.defs[name]
            if "enum" in d or d.get("type") != "object":
                continue
            interfaces += self.emit_interface(name, d)
            interfaces.append("")
        enums: list[str] = []
        for name in sorted(n for n, d in self.defs.items() if "enum" in d):
            enums += self.emit_enum(name, self.defs[name]["enum"], self.defs[name].get("description"))
            enums.append("")
        for name in sorted(self.inline_enums):
            enums += self.emit_enum(name, self.inline_enums[name], None)
            enums.append("")
        unions: list[str] = []
        for name in sorted(self.unions):
            unions += self.emit_union(name)
            unions.append("")
        commands = [
            "/** Débits par connexion (trames par seconde), tels que le noyau les applique. */",
            "export const RATES: Readonly<Record<string, number>> = {",
            *[f"  {k}: {float(v):g}," for k, v in sorted(rates.items())],
            "};",
            "",
            "/** Les rôles que chaque commande exige (au moins un). */",
            "export const REQUIRES: Readonly<Record<string, readonly Role[]>> = {",
            *[f"  {k}: [{', '.join(json.dumps(r) for r in sorted(v))}]," for k, v in sorted(requires.items())],
            "};",
        ]
        header = [
            "// <auto-generated>",
            "// Protocole du monde de Mika (mika.world/1) — généré par frontend/Web/tools/gen_world_protocol.py",
            "// depuis le schéma JSON du noyau (backendv2 : mika.adapters.world.protocol.json_schema()).",
            "// NE PAS ÉDITER À LA MAIN : régénérer après un changement du contrat.",
            "// </auto-generated>",
            "",
            f"export const PROTOCOL = {json.dumps(protocol)};",
            'export const PATH = "/ws/world";',
            "",
        ]
        return "\n".join(header + unions + enums + interfaces + commands + [""])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="échoue si le fichier généré n'est plus à jour")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    from mika.adapters.world import protocol  # noqa: PLC0415 — après l'ajout au chemin

    rates = dict(protocol.RATES)
    requires = {k: [r.value for r in v] for k, v in protocol.REQUIRES.items()}
    text = Gen(protocol.json_schema()).render(protocol.PROTOCOL, rates, requires)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} n'est plus à jour : relancer sans --check", file=sys.stderr)
            return 1
        print("à jour")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"écrit {args.out.relative_to(ROOT)} ({len(text.splitlines())} lignes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
