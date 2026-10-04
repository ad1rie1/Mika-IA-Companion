"""Génère les types C# du protocole ``mika.world/1`` depuis le schéma JSON publié par le noyau.

Le noyau (``backendv2``) fait foi : ``mika.adapters.world.protocol.json_schema()`` décrit les trames dans les
deux sens et la définition du monde. Ce script en tire un seul fichier C# pour Unity, si bien qu'un champ ajouté
côté noyau arrive côté moteur par une régénération, jamais par une recopie à la main.

    backendv2/.venv/bin/python frontend/Unity/tools/gen_world_protocol.py            # écrit le fichier
    backendv2/.venv/bin/python frontend/Unity/tools/gen_world_protocol.py --check    # échoue s'il a vieilli

Ce qui est produit (``Assets/Mika/Runtime/Protocol/Generated/WorldProtocol.g.cs``) :

- une énumération par énumération du schéma (valeur JSON portée par ``[EnumMember]``) ;
- une classe par objet, propriétés en PascalCase, valeurs par défaut du schéma en initialiseurs ;
- une classe de base abstraite par union discriminée (``ClientFrame`` par ``type``, ``Location`` par ``kind``…),
  lue par ``DiscriminatedConverter`` (écrit à la main, à côté) ;
- les débits et les rôles exigés par commande (``Commands``).

Une propriété annulable dont le défaut n'est pas ``null`` (``Affordance.duration_s`` : ``null`` = sans fin) est
écrite même nulle — l'omettre ferait prendre au noyau la durée par défaut.
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

OUT = ROOT / "frontend" / "Unity" / "Mika" / "Assets" / "Mika" / "Runtime" / "Protocol" / "Generated" / "WorldProtocol.g.cs"

# Le nom C# d'une union discriminée, reconnue par l'ensemble de ses membres. Une union inconnue est une erreur :
# on la nomme ici plutôt que de laisser le générateur inventer un nom qui changerait d'une version à l'autre.
UNIONS: dict[frozenset[str], str] = {
    frozenset({"InRoom", "On", "In", "Held"}): "Location",
    frozenset({"ActorMoved", "ActorBusy", "ObjectMoved", "ObjectSet", "ObjectGone"}): "Change",
    frozenset({"DefPut", "DefRemove"}): "DefChange",
    frozenset({"RoomDef", "PlaceDef", "ArchetypeDef", "ObjectDef", "ActorDef"}): "DefItem",
    frozenset({"Progress", "Finished", "Settled", "NpcUpdate", "Sound", "Loaded"}): "ReportBody",
}

# Ce qui reste petit (une place, un nombre de places, un pas, une durée de bail) est un ``int`` ; le reste des
# entiers (instants en µs, seq, rev) est un ``long``.
INT_FIELDS = {"slot", "capacity", "step", "surface_slots", "container_slots", "ttl_ms"}

CS_KEYWORDS = {"object", "in", "base", "params", "event", "string", "operator", "is", "as", "out", "ref"}


def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s.:/]+", name) if p)


def summary(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    out = [f"{indent}/// <summary>"]
    out += [f"{indent}/// {ln}".rstrip() for ln in lines]
    out.append(f"{indent}/// </summary>")
    return out


class Gen:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.defs: dict[str, dict[str, Any]] = {}
        for section in ("client", "server", "world"):
            for name, d in schema[section].get("$defs", {}).items():
                if name in self.defs and self.defs[name] != d:
                    raise SystemExit(f"définition {name} différente selon les sections")
                self.defs[name] = d
        world = {k: v for k, v in schema["world"].items() if k not in ("$defs",)}
        self.defs["WorldDef"] = world
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
    def cs_type(self, owner: str, prop: str, node: dict[str, Any]) -> tuple[str, bool]:
        """(type C#, annulable dans le schéma)."""
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            nullable = len(options) < len(node["anyOf"])
            if len(options) != 1:
                raise SystemExit(f"{owner}.{prop} : anyOf non pris en charge")
            t, _ = self.cs_type(owner, prop, options[0])
            return t, nullable
        if "$ref" in node:
            return node["$ref"].split("/")[-1], False
        if "discriminator" in node and "oneOf" in node:
            return self.union_name(node), False
        if "const" in node:
            return "string", False
        if "enum" in node:
            name = owner + pascal(prop)
            self.inline_enums[name] = list(node["enum"])
            return name, False
        t = node.get("type")
        if t == "string":
            return "string", False
        if t == "integer":
            return ("int" if prop in INT_FIELDS else "long"), False
        if t == "number":
            return "double", False
        if t == "boolean":
            return "bool", False
        if t == "array":
            inner, _ = self.cs_type(owner, prop, node.get("items", {}))
            return f"List<{inner}>", False
        if t == "object" and isinstance(node.get("additionalProperties"), dict):
            inner, _ = self.cs_type(owner, prop, node["additionalProperties"])
            return f"Dictionary<string, {inner}>", False
        raise SystemExit(f"{owner}.{prop} : type non pris en charge {node}")

    def is_enum(self, t: str) -> bool:
        return t in self.inline_enums or ("enum" in self.defs.get(t, {}))

    def is_value(self, t: str) -> bool:
        return t in ("int", "long", "double", "bool") or self.is_enum(t)

    def default_expr(self, t: str, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if t in ("int", "long"):
            return f"{int(value)}" + ("L" if t == "long" else "")
        if t == "double":
            v = float(value)
            return repr(v) if "." in repr(v) or "e" in repr(v) else f"{v}.0"
        if t == "string":
            return json.dumps(value, ensure_ascii=False)
        if self.is_enum(t):
            return f"global::Mika.World.Protocol.{t}.{pascal(str(value))}"
        if t.startswith("List<") and value == []:
            return f"new {t}()"
        if t.startswith("Dictionary<") and value == {}:
            return f"new {t}()"
        raise SystemExit(f"défaut non pris en charge : {t} = {value!r}")

    # --- émission -----------------------------------------------------------------------------------------
    def emit_enum(self, name: str, values: list[str], doc: str | None) -> list[str]:
        out = summary(doc, "    ")
        out.append("    [JsonConverter(typeof(StringEnumConverter))]")
        out.append(f"    public enum {name}")
        out.append("    {")
        for v in values:
            out.append(f"        [EnumMember(Value = {json.dumps(v)})] {pascal(v)},")
        out.append("    }")
        return out

    def emit_class(self, name: str, d: dict[str, Any]) -> list[str]:
        props = d.get("properties", {})
        required = set(d.get("required", []))
        union = self.union_of.get(name)
        base = f" : {union[0]}" if union else ""
        out = summary(d.get("description"), "    ")
        out.append(f"    public sealed partial class {name}{base}")
        out.append("    {")
        for prop, node in props.items():
            if union and prop == union[1]:
                out.append(f"        [JsonProperty({json.dumps(prop)}, Order = -2)]")
                out.append(f"        public override string {pascal(prop)} => {json.dumps(union[2])};")
                out.append("")
                continue
            if "const" in node:
                out.append(f"        [JsonProperty({json.dumps(prop)}, Order = -1)]")
                out.append(f"        public string {pascal(prop)} => {json.dumps(node['const'])};")
                out.append("")
                continue
            t, nullable = self.cs_type(name, prop, node)
            has_default = "default" in node
            default = node.get("default")
            optional = prop not in required
            cs_t = t
            if (nullable or (optional and not has_default)) and self.is_value(t):
                cs_t = t + "?"
            attrs = [json.dumps(prop)]
            if nullable and default is not None:
                attrs.append("NullValueHandling = NullValueHandling.Include")
            init = self.default_expr(t, default) if has_default else None
            if init is None and not nullable and not optional and t.startswith(("List<", "Dictionary<")):
                init = f"new {t}()"
            out += summary(node.get("description"), "        ")
            out.append(f"        [JsonProperty({', '.join(attrs)})]")
            member = pascal(prop)
            if member == name:
                member += "Value"
            line = f"        public {cs_t} {member} {{ get; set; }}"
            if init is not None:
                line += f" = {init};"
            out.append(line)
            out.append("")
        if out[-1] == "":
            out.pop()
        out.append("    }")
        return out

    def emit_union(self, name: str) -> list[str]:
        prop, members = self.unions[name]
        out = [f"    /// <summary>Union discriminée par « {prop} » : "
               + ", ".join(f"{m} (« {v} »)" for v, m in members) + ".</summary>"]
        out.append(f"    [JsonConverter(typeof({name}.Converter))]")
        out.append(f"    public abstract partial class {name}")
        out.append("    {")
        out.append(f"        [JsonProperty({json.dumps(prop)}, Order = -2)]")
        out.append(f"        public abstract string {pascal(prop)} {{ get; }}")
        out.append("")
        out.append(f"        /// <summary>Le type C# d'une valeur du discriminant ; <c>null</c> si inconnue.</summary>")
        out.append(f"        public static Type TypeOf(string tag) => tag switch")
        out.append("        {")
        for v, m in members:
            out.append(f"            {json.dumps(v)} => typeof({m}),")
        out.append("            _ => null,")
        out.append("        };")
        out.append("")
        out.append(f"        internal sealed class Converter : DiscriminatedConverter<{name}>")
        out.append("        {")
        out.append(f"            public Converter() : base({json.dumps(prop)}, TypeOf) {{ }}")
        out.append("        }")
        out.append("    }")
        return out

    def render(self, rates: dict[str, float], requires: dict[str, list[str]]) -> str:
        # Les classes d'abord (elles enregistrent les énumérations en ligne au passage).
        classes: list[str] = []
        for name in sorted(self.defs):
            d = self.defs[name]
            if "enum" in d:
                continue
            if d.get("type") != "object":
                continue
            classes += self.emit_class(name, d)
            classes.append("")
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
        cmds = ["    /// <summary>Débits par connexion (trames par seconde) et rôles exigés, tels que le noyau les applique.</summary>",
                "    public static class Commands",
                "    {",
                "        public static readonly IReadOnlyDictionary<string, double> Rates = new Dictionary<string, double>",
                "        {"]
        cmds += [f"            [{json.dumps(k)}] = {float(v)!r}," for k, v in sorted(rates.items())]
        cmds += ["        };", "",
                 "        public static readonly IReadOnlyDictionary<string, Role[]> Requires = new Dictionary<string, Role[]>",
                 "        {"]
        cmds += [f"            [{json.dumps(k)}] = new[] {{ {', '.join('Role.' + pascal(r) for r in sorted(v))} }},"
                 for k, v in sorted(requires.items())]
        cmds += ["        };", "    }"]
        header = [
            "// <auto-generated>",
            "// Protocole du monde de Mika (mika.world/1) — généré par frontend/Unity/tools/gen_world_protocol.py",
            "// depuis le schéma JSON du noyau (backendv2 : mika.adapters.world.protocol.json_schema()).",
            "// NE PAS ÉDITER À LA MAIN : régénérer après un changement du contrat.",
            "// </auto-generated>",
            "#nullable disable",
            "using System;",
            "using System.Collections.Generic;",
            "using System.Runtime.Serialization;",
            "using Newtonsoft.Json;",
            "using Newtonsoft.Json.Converters;",
            "",
            "namespace Mika.World.Protocol",
            "{",
            f"    public static class Wire",
            "    {",
            '        public const string Protocol = "mika.world/1";',
            '        public const string Path = "/ws/world";',
            "    }",
            "",
        ]
        body = header + unions + enums + classes + cmds + ["}", ""]
        return "\n".join(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="échoue si le fichier généré n'est plus à jour")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    from mika.adapters.world import protocol  # noqa: PLC0415 — après l'ajout au chemin

    schema = protocol.json_schema()
    rates = dict(protocol.RATES)
    requires = {k: [r.value for r in v] for k, v in protocol.REQUIRES.items()}
    text = Gen(schema).render(rates, requires)
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
