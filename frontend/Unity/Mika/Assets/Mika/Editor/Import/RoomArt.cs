using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;

namespace Mika.Editor.Import
{
    /// <summary>
    /// Ce que l'export Blender (<c>frontend/Web/assets-src/blender/export_unity.py</c>) écrit à côté des FBX :
    /// <c>room_layout.json</c> (où va chaque objet, ses enfants mobiles, ses surfaces, les ancres de lumière) et
    /// <c>materials.json</c> (les matériaux tels que Blender les rend). Lu tel quel, sans rien deviner.
    /// </summary>
    public sealed class RoomLayout
    {
        [JsonProperty("format")] public string Format;
        [JsonProperty("objects")] public List<LayoutObject> Objects = new List<LayoutObject>();
        [JsonProperty("light_anchors")] public List<LightAnchor> LightAnchors = new List<LightAnchor>();
        [JsonProperty("room")] public LayoutBox Room;

        public static RoomLayout Read(string path) => JsonConvert.DeserializeObject<RoomLayout>(File.ReadAllText(path));
    }

    public sealed class LayoutBox
    {
        [JsonProperty("min")] public V3 Min;
        [JsonProperty("max")] public V3 Max;
    }

    public sealed class V3
    {
        [JsonProperty("x")] public float X;
        [JsonProperty("y")] public float Y;
        [JsonProperty("z")] public float Z;
    }

    public sealed class LayoutObject
    {
        [JsonProperty("id")] public string Id;
        [JsonProperty("category")] public string Category;
        [JsonProperty("asset")] public string Asset;
        [JsonProperty("fbx")] public string Fbx;
        [JsonProperty("pos")] public V3 Pos;
        [JsonProperty("yaw")] public float Yaw;
        [JsonProperty("size")] public V3 Size;
        [JsonProperty("materials")] public List<string> Materials = new List<string>();
        [JsonProperty("emissive")] public bool Emissive;
        [JsonProperty("children")] public List<LayoutChild> Children = new List<LayoutChild>();
        [JsonProperty("surfaces")] public List<LayoutSurface> Surfaces = new List<LayoutSurface>();
        [JsonProperty("triangles")] public int Triangles;
    }

    public sealed class LayoutChild
    {
        [JsonProperty("name")] public string Name;
        [JsonProperty("pivot")] public V3 Pivot;
        [JsonProperty("motion")] public Motion Motion;
    }

    public sealed class Motion
    {
        /// <summary>hinge, slide, rotate, scale, toggle.</summary>
        [JsonProperty("type")] public string Type;
        [JsonProperty("axis")] public string Axis;
        [JsonProperty("opens_toward")] public V3 OpensToward;
        [JsonProperty("dir")] public V3 Dir;
    }

    public sealed class LayoutSurface
    {
        [JsonProperty("piece")] public string Piece;
        [JsonProperty("height")] public float Height;
        [JsonProperty("min")] public V3 Min;
        [JsonProperty("max")] public V3 Max;
    }

    public sealed class LightAnchor
    {
        [JsonProperty("name")] public string Name;
        [JsonProperty("pos")] public V3 Pos;
        [JsonProperty("object")] public string Object;
        [JsonProperty("local")] public V3 Local;
    }

    public sealed class RoomMaterials
    {
        [JsonProperty("materials")] public Dictionary<string, MaterialSpec> Materials = new Dictionary<string, MaterialSpec>();

        public static RoomMaterials Read(string path) => JsonConvert.DeserializeObject<RoomMaterials>(File.ReadAllText(path));
    }

    public sealed class MaterialSpec
    {
        [JsonProperty("base_color")] public ColorSpec BaseColor;
        [JsonProperty("roughness")] public float Roughness = 0.6f;
        [JsonProperty("metallic")] public float Metallic;
        [JsonProperty("emission")] public EmissionSpec Emission;
        [JsonProperty("alpha")] public float Alpha = 1f;
        [JsonProperty("blend")] public string Blend = "opaque";
        [JsonProperty("double_sided")] public bool DoubleSided;
        [JsonProperty("textures")] public TextureSpec Textures;
    }

    public sealed class ColorSpec
    {
        [JsonProperty("linear")] public float[] Linear;
        [JsonProperty("srgb_hex")] public string SrgbHex;
    }

    public sealed class EmissionSpec
    {
        [JsonProperty("color")] public ColorSpec Color;
        [JsonProperty("strength")] public float Strength;
    }

    public sealed class TextureSpec
    {
        [JsonProperty("base")] public string Base;
        [JsonProperty("normal")] public string Normal;
        [JsonProperty("roughness")] public string Roughness;
        [JsonProperty("emission")] public string Emission;
    }
}
