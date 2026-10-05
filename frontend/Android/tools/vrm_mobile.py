#!/usr/bin/env python3
"""
Préparer le VRM de Mika pour l'application Android (rendu natif Filament).

Le modèle du client web (`frontend/Web/public/models/default.vrm`, ~100 Mo) ne passe pas tel quel sur un téléphone :
son maillage du visage porte 342 morphoses par primitive (Filament en accepte 256 au plus), stockées pleines, avec
leurs normales, et ses textures sont en 2048 px avec des normal maps et des masques qu'un rendu toon n'utilise pas.
Ce script écrit un GLB allégé qui garde le VRM intact pour tout le reste (squelette, humanoïde, groupes d'expressions,
regard, ressorts, matériaux MToon) :

  - morphoses : seules celles qu'une expression du modèle référence, plus la physiologie du visage (rougeur, larmes,
    pupilles) et les visèmes `vrc.v_*` ; les autres disparaissent et les liens des groupes sont renumérotés ;
  - chaque morphose est rangée en accesseur *sparse* (une expression ne déplace que quelques centaines de sommets),
    positions et normales — sans perte : seuls les zéros disparaissent ;
  - textures : toutes celles que les matériaux citent (glTF et MToon : couleur, ombre, normal map, rim, contour,
    émission), en pleine résolution par défaut (la propriétaire veut la meilleure qualité possible) ; `--texture N`
    les réduit à N px de côté.

Le modèle est sous licence de l'acheteur : la sortie n'est pas versionnée (assets de l'app, ignorés par git).

    python3 frontend/Android/tools/vrm_mobile.py [--src frontend/Web/public/models/default.vrm] \
        [--out frontend/Android/app/src/main/assets/avatar3d/mika.glb] [--texture 0]
"""
import argparse
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "frontend/Web/public/models/default.vrm"
OUT = REPO / "frontend/Android/app/src/main/assets/avatar3d/mika.glb"

# Les morphoses que le visage lit sans passer par un groupe du modèle (FacePhysiology, LipSyncController).
RAW_MORPHS = {"FaceRed", "EyeWatery", "Tear", "EyeDilationLeft", "EyeDilationRight", "EyeConstrictLeft",
              "EyeConstrictRight"}
RAW_PREFIXES = ("vrc.v_",)

COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def read_glb(path):
    data = Path(path).read_bytes()
    magic, version, _ = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise SystemExit(f"{path} n'est pas un GLB 2.0")
    off, doc, binary = 12, None, b""
    while off < len(data):
        length, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + length]
        if kind == 0x4E4F534A:
            doc = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
        off += 8 + length
    return doc, binary


def write_glb(path, doc, binary):
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()
    raw += b" " * (-len(raw) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(raw) + 8 + len(binary)
    out = struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(raw), 0x4E4F534A) + raw
    out += struct.pack("<II", len(binary), 0x004E4942) + binary
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(out)


def accessor_array(doc, binary, index):
    """Les valeurs d'un accesseur dense, en tableau numpy (n, largeur)."""
    acc = doc["accessors"][index]
    if "sparse" in acc:
        raise SystemExit(f"accesseur {index} déjà sparse : non prévu")
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(COMPONENT[acc["componentType"]])
    width = WIDTH[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", 0) or dtype.itemsize * width
    count = acc["count"]
    if stride == dtype.itemsize * width:
        arr = np.frombuffer(binary, dtype=dtype, count=count * width, offset=start).reshape(count, width)
    else:
        rows = [np.frombuffer(binary, dtype=dtype, count=width, offset=start + k * stride) for k in range(count)]
        arr = np.stack(rows)
    return arr.copy()


class Packer:
    """Le nouveau tampon : des vues alignées sur 4 octets, des accesseurs neufs."""

    def __init__(self):
        self.chunks, self.size, self.views, self.accessors = [], 0, [], []

    def view(self, data, target=None):
        pad = -self.size % 4
        if pad:
            self.chunks.append(b"\0" * pad)
            self.size += pad
        v = {"buffer": 0, "byteOffset": self.size, "byteLength": len(data)}
        if target:
            v["target"] = target
        self.chunks.append(data)
        self.size += len(data)
        self.views.append(v)
        return len(self.views) - 1

    def dense(self, src_acc, arr, target=None):
        acc = {k: v for k, v in src_acc.items() if k not in ("bufferView", "byteOffset", "sparse")}
        acc["bufferView"] = self.view(np.ascontiguousarray(arr).tobytes(), target)
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def fresh(self, arr, component, kind, target=None, normalized=False, bounds=False):
        """Un accesseur neuf sur un tableau (n, largeur)."""
        acc = {"componentType": component, "type": kind, "count": int(arr.shape[0]),
               "bufferView": self.view(np.ascontiguousarray(arr).tobytes(), target)}
        if normalized:
            acc["normalized"] = True
        if bounds:
            acc["min"] = [float(x) for x in arr.min(axis=0)]
            acc["max"] = [float(x) for x in arr.max(axis=0)]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def sparse_vec3(self, deltas):
        """Une morphose (n, 3) float en accesseur sparse : seuls les sommets qui bougent sont écrits."""
        moving = np.nonzero(np.abs(deltas).max(axis=1) > 1e-7)[0]
        if moving.size == 0:
            moving = np.array([0])  # un sparse compte au moins une entrée
        values = deltas[moving].astype(np.float32)
        big = deltas.shape[0] > 65535
        indices = moving.astype(np.uint32 if big else np.uint16)
        acc = {
            "componentType": 5126, "type": "VEC3", "count": int(deltas.shape[0]),
            "min": [float(x) for x in deltas.min(axis=0)], "max": [float(x) for x in deltas.max(axis=0)],
            "sparse": {
                "count": int(moving.size),
                "indices": {"bufferView": self.view(indices.tobytes()), "componentType": 5125 if big else 5123},
                "values": {"bufferView": self.view(values.tobytes())},
            },
        }
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def binary(self):
        return b"".join(self.chunks)


def kept_targets(doc):
    """Par maillage, les indices de morphoses gardés (dans l'ordre d'origine)."""
    vrm = doc["extensions"]["VRM"]
    bound = {}
    for g in vrm["blendShapeMaster"]["blendShapeGroups"]:
        for b in g.get("binds", []):
            bound.setdefault(b["mesh"], set()).add(b["index"])
    keep = {}
    for mi, mesh in enumerate(doc["meshes"]):
        names = mesh.get("extras", {}).get("targetNames") or []
        n = len(mesh["primitives"][0].get("targets", []))
        raw = {i for i, name in enumerate(names) if name in RAW_MORPHS or name.startswith(RAW_PREFIXES)}
        keep[mi] = sorted(bound.get(mi, set()) | raw) if mi in bound or raw else list(range(n))
        # Un petit maillage (vêtements) garde tout : quelques morphoses, presque rien en sparse.
        if n <= 40:
            keep[mi] = list(range(n))
    return keep


def resize_png(data, size):
    img = Image.open(io.BytesIO(data))
    if not size or max(img.size) <= size:
        return data, img.size  # telle quelle, octet pour octet
    ratio = size / max(img.size)
    img = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), img.size


def sub_mesh(doc, binary, pk, prim, kept, names):
    """
    Une primitive en maillage autonome : ses seuls sommets (renumérotés), ses indices, et les morphoses gardées
    qui déplacent au moins un de ses sommets. Rend la primitive et les noms de ses morphoses.
    """
    idx = accessor_array(doc, binary, prim["indices"]).ravel().astype(np.int64)
    used = np.unique(idx)
    remap = np.full(int(used.max()) + 1, -1, dtype=np.int64)
    remap[used] = np.arange(used.size)
    new_idx = remap[idx]
    big = used.size > 65535
    out = {k: v for k, v in prim.items() if k not in ("attributes", "indices", "targets")}
    out["indices"] = pk.fresh(new_idx.astype(np.uint32 if big else np.uint16).reshape(-1, 1),
                              5125 if big else 5123, "SCALAR", ELEMENT_ARRAY_BUFFER)
    attrs = {}
    for key, acc_index in prim["attributes"].items():
        src = doc["accessors"][acc_index]
        arr = accessor_array(doc, binary, acc_index)[used]
        attrs[key] = pk.fresh(arr, src["componentType"], src["type"], ARRAY_BUFFER,
                              normalized=src.get("normalized", False), bounds=key == "POSITION")
    out["attributes"] = attrs
    targets, part_names = [], []
    for t in kept:
        src_t = prim["targets"][t]
        deltas = {k: accessor_array(doc, binary, src_t[k])[used] for k in ("POSITION", "NORMAL") if k in src_t}
        if all(np.abs(d).max() <= 1e-7 for d in deltas.values()):
            continue
        targets.append({k: pk.sparse_vec3(d) for k, d in deltas.items()})
        part_names.append(names[t])
    if targets:
        out["targets"] = targets
    return out, part_names


def convert(src, out, texture):
    doc, binary = read_glb(src)
    original_names = [m.get("extras", {}).get("targetNames") or [] for m in doc["meshes"]]
    pk = Packer()
    remap_acc = {}

    def copy(index, target=None):
        if index not in remap_acc:
            remap_acc[index] = pk.dense(doc["accessors"][index], accessor_array(doc, binary, index), target)
        return remap_acc[index]

    keep = kept_targets(doc)
    stats = {}
    # Le visage est un maillage à plusieurs primitives (peau, yeux, expressions, cheveux…) qui partagent tous leurs
    # sommets : chaque primitive portait les 167 morphoses, même là où elles valent zéro, et gltfio en calculait
    # les repères tangents pour chacune (18 s de chargement sur le téléphone). Il est découpé : un maillage par
    # primitive, avec ses seuls sommets et les seules morphoses qui les déplacent. Les liens d'expression
    # désignent désormais une morphose par son nom (`morphName`), que chaque morceau retrouve dans ses `targetNames`.
    meshes, mesh_parts = [], {}
    for mi, mesh in enumerate(doc["meshes"]):
        kept = keep[mi]
        names = mesh.get("extras", {}).get("targetNames") or []
        weights = mesh.get("weights")
        prims = mesh["primitives"]
        split = len(prims) > 1 and bool(prims[0].get("targets"))
        parts = []
        if not split:
            for prim in prims:
                prim["attributes"] = {k: copy(v, ARRAY_BUFFER) for k, v in prim["attributes"].items()}
                if "indices" in prim:
                    prim["indices"] = copy(prim["indices"], ELEMENT_ARRAY_BUFFER)
                targets = prim.get("targets", [])
                if targets:
                    prim["targets"] = [{k: pk.sparse_vec3(accessor_array(doc, binary, targets[t][k]))
                                        for k in ("POSITION", "NORMAL") if k in targets[t]}
                                       for t in kept]
            if names:
                mesh["extras"]["targetNames"] = [names[t] for t in kept]
            if weights is not None:
                mesh["weights"] = [weights[t] for t in kept]
            parts.append(mesh)
            stats[mesh.get("name", mi)] = (len(names), len(kept))
        else:
            for prim in prims:
                part, part_names = sub_mesh(doc, binary, pk, prim, kept, names)
                mat = doc["materials"][prim["material"]]["name"] if "material" in prim else str(len(parts))
                new = {"name": f"{mesh.get('name', mi)}.{mat}", "primitives": [part]}
                if part_names:
                    new["extras"] = {"targetNames": part_names}
                    if weights is not None:
                        new["weights"] = [weights[names.index(n)] for n in part_names]
                parts.append(new)
                stats[new["name"]] = (len(kept), len(part_names))
        mesh_parts[mi] = list(range(len(meshes), len(meshes) + len(parts)))
        meshes.extend(parts)
    doc["meshes"] = meshes

    # Chaque morceau a son nœud (gltfio en fait une entité), frère du nœud d'origine, même peau, même place.
    scene_roots = doc["scenes"][doc.get("scene", 0)]["nodes"]
    parent_of = {c: i for i, n in enumerate(doc["nodes"]) for c in n.get("children", [])}
    for ni in range(len(doc["nodes"])):
        node = doc["nodes"][ni]
        if "mesh" not in node:
            continue
        parts = mesh_parts[node["mesh"]]
        node["mesh"] = parts[0]
        for k, part in enumerate(parts[1:], start=1):
            twin = {key: node[key] for key in ("translation", "rotation", "scale", "skin") if key in node}
            twin["name"] = doc["meshes"][part]["name"]
            twin["mesh"] = part
            doc["nodes"].append(twin)
            new_index = len(doc["nodes"]) - 1
            if ni in parent_of:
                doc["nodes"][parent_of[ni]]["children"].append(new_index)
            else:
                scene_roots.append(new_index)

    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            skin["inverseBindMatrices"] = copy(skin["inverseBindMatrices"])

    # Groupes d'expressions : chaque lien nomme sa morphose ; ceux vers une morphose écartée disparaissent.
    vrm = doc["extensions"]["VRM"]
    for g in vrm["blendShapeMaster"]["blendShapeGroups"]:
        binds = []
        for b in g.get("binds", []):
            if b["index"] in keep[b["mesh"]]:
                name = original_names[b["mesh"]][b["index"]]
                binds.append({"mesh": mesh_parts[b["mesh"]][0], "index": keep[b["mesh"]].index(b["index"]),
                              "weight": b["weight"], "morphName": name})
        g["binds"] = binds
    for ann in vrm.get("firstPerson", {}).get("meshAnnotations", []):
        if ann.get("mesh") in mesh_parts:
            ann["mesh"] = mesh_parts[ann["mesh"]][0]

    # Textures : toutes celles qu'un matériau cite (glTF ou MToon) ; les autres (aucune en principe) disparaissent.
    used_tex = []

    def use(index):
        if index is not None and index not in used_tex:
            used_tex.append(index)

    for mat in doc["materials"]:
        for key in ("normalTexture", "emissiveTexture", "occlusionTexture"):
            use(mat.get(key, {}).get("index"))
        use(mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index"))
    for mp in vrm.get("materialProperties", []):
        for v in mp.get("textureProperties", {}).values():
            use(v)
    tex_remap = {old: new for new, old in enumerate(used_tex)}
    img_remap, images, textures = {}, [], []
    for old in used_tex:
        tex = dict(doc["textures"][old])
        src_img = tex["source"]
        if src_img not in img_remap:
            im = doc["images"][src_img]
            view = doc["bufferViews"][im["bufferView"]]
            data = binary[view.get("byteOffset", 0): view.get("byteOffset", 0) + view["byteLength"]]
            png, size = resize_png(data, texture)
            img_remap[src_img] = len(images)
            images.append({"name": im.get("name"), "mimeType": im.get("mimeType", "image/png"), "bufferView": pk.view(png)})
            print(f"texture {im.get('name')}: {size[0]}x{size[1]}, {len(png) // 1024} Ko")
        tex["source"] = img_remap[src_img]
        textures.append(tex)
    for mat in doc["materials"]:
        for key in ("normalTexture", "emissiveTexture", "occlusionTexture"):
            if key in mat:
                mat[key]["index"] = tex_remap[mat[key]["index"]]
        info = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if info:
            info["index"] = tex_remap[info["index"]]
    for mp in vrm.get("materialProperties", []):
        props = mp.get("textureProperties", {})
        mp["textureProperties"] = {k: tex_remap[v] for k, v in props.items() if v in tex_remap}

    doc["images"], doc["textures"] = images, textures
    doc["accessors"], doc["bufferViews"] = pk.accessors, pk.views
    data = pk.binary()
    doc["buffers"] = [{"byteLength": len(data)}]
    write_glb(out, doc, data)
    for name, (before, after) in stats.items():
        if before:
            print(f"morphoses {name}: {before} → {after}")
    print(f"{out} : {Path(out).stat().st_size / 1e6:.1f} Mo (depuis {Path(src).stat().st_size / 1e6:.1f} Mo)")


def main():
    parser = argparse.ArgumentParser(description="VRM de Mika pour l'application Android")
    parser.add_argument("--src", default=str(SRC))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--texture", type=int, default=0, help="côté maximal des textures en px (0 : pleine résolution)")
    args = parser.parse_args()
    convert(args.src, args.out, args.texture)


if __name__ == "__main__":
    main()
