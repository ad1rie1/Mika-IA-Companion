using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Mika.Avatar
{
    /// <summary>
    /// Les noms des expressions que le visage enregistre lui-même sur le modèle, et la liste de ce qu'il en
    /// retire. Portage des conventions de <c>frontend/src/vtuber/faceRig.ts</c>.
    /// </summary>
    /// <remarks>
    /// Deux familles d'expressions ajoutées au <c>VRM10Object</c> (sur une copie, jamais sur l'asset importé) :
    /// <list type="bullet">
    /// <item><c>clean:&lt;Groupe&gt;</c> — la copie d'un groupe du modèle dont chaque liaison vers un symbole
    /// manga ou vers une direction de regard a été retirée ;</item>
    /// <item><c>raw:&lt;morph&gt;</c> — un morph seul, exposé comme expression (rougeur, larmes, visèmes
    /// VRChat…) : le modèle Perula porte 342 morphs mais n'en expose que 118 à travers ses groupes.</item>
    /// </list>
    /// Les deux préfixes contiennent un « : », qu'aucun groupe d'auteur ne porte : pas de collision possible avec
    /// les noms du modèle.
    /// </remarks>
    public static class FaceNames
    {
        public const string CleanPrefix = "clean:";
        public const string RawPrefix = "raw:";

        public static string Clean(string group) => CleanPrefix + group;
        public static string Raw(string morph) => RawPrefix + morph;

        /// <summary>
        /// Morphs qui DESSINENT un symbole manga au lieu de bouger un visage : larmes et rougeur (que la couche
        /// physiologique gère sur leur propre horloge lente), gouttes de sueur, ombres de déprime, yeux en
        /// spirale / cœur / étoile / « &gt;&lt; », yeux noirs ou blancs, pupilles en tête d'épingle, reflets
        /// démesurés. Les groupes de l'auteur les mêlent au vrai mouvement du visage — <c>Shocked</c> (surprise)
        /// dessine des yeux en spirale et une goutte de sueur, <c>Sad1</c> une larme à toute intensité.
        /// </summary>
        public static readonly IReadOnlyCollection<string> SymbolMorphs = new HashSet<string>(StringComparer.Ordinal)
        {
            "Tear", "Tear2", "TearFlow", "EyeWatery",
            "FaceRed", "FaceRed2", "FaceRed3",
            "FaceSweat", "FaceSweat2", "FaceShadow", "FaceShadow2", "FaceShadow3",
            "FaceSnot", "FaceSnotLong", "FaceSnotBubbles", "FaceSnotBubblesBig", "FaceSnotBubblesSmall",
            "Eye@@", "EyeStar", "EyeHeart", "EyeHeartSmall", "Eye><", "Eye0 0", "Eye0 0VSmall", "Eye0 0USmall",
            "EyeBlack", "EyeWhite", "EyeStare", "EyeHide", "EyeBlackCircles",
            "EyeIrisWhite", "EyeIrisClear", "EyeIrisSmall", "EyeIrisBig",
            "EyePupilBlackLine", "EyePupilCircle", "EyePupilSmall",
            "EyeHighlightHide", "EyeHighlightBig", "EyeHighlightDown", "EyeHighlightStar", "EyeHighlightHeart",
            "Mouth△", "Mouth^", "Mouthω", "Mouth□",
        };

        static readonly Regex GazeMorph = new Regex("^eyeLook", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        /// <summary>
        /// Morphs de direction du regard : c'est le regard qui décide où pointent les yeux (os, saccades,
        /// évitements) — une expression qui roule aussi les iris vers le haut (<c>Shy</c>, <c>Disgust</c>) le
        /// combattrait.
        /// </summary>
        public static bool IsGazeMorph(string morph) => morph != null && GazeMorph.IsMatch(morph);

        /// <summary>Ce que le nettoyage retire d'un groupe : symboles et regard.</summary>
        public static bool IsStripped(string morph) =>
            morph != null && (((HashSet<string>)SymbolMorphs).Contains(morph) || IsGazeMorph(morph));
    }
}
