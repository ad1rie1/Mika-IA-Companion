using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Mika.Avatar
{
    /// <summary>
    /// La cadence de l'estimation texte, partagée par tout ce qui doit lire le même débit (portage de
    /// <c>frontend/src/audio/cadence.ts</c>).
    /// </summary>
    public static class SpeechCadence
    {
        /// <summary>Cadence par défaut, en millisecondes par caractère prononcé.</summary>
        public const float DefaultMsPerChar = 60f;

        /// <summary>
        /// La cadence suit le débit de l'énoncé. À 60 ms/car fixes, une réponse excitée (débit 1,15) laissait la
        /// bouche bouger après la fin de la voix, et une réponse blasée (0,8) la fermait alors qu'il restait un
        /// cinquième de l'audio. Débit borné à [0,5 ; 2] comme celui d'une voix.
        /// </summary>
        public static float MsPerCharForRate(float rate)
        {
            float r = !float.IsNaN(rate) && !float.IsInfinity(rate) && rate > 0f ? Math.Max(0.5f, Math.Min(2f, rate)) : 1f;
            return DefaultMsPerChar / r;
        }

        /// <summary>
        /// Débit d'une voix selon l'émotion (<c>TTSService.ts::EMOTION_VOICE</c>) — utile à l'appelant qui veut
        /// passer à <see cref="MikaFace.Speak"/> le débit que la voix du web aurait eu.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, float> EmotionRate = new Dictionary<string, float>
        {
            ["neutral"] = 1f, ["happy"] = 1.05f, ["excited"] = 1.15f, ["love"] = 0.9f, ["proud"] = 0.95f,
            ["grateful"] = 0.95f, ["playful"] = 1.1f, ["amused"] = 1.05f, ["hopeful"] = 1f, ["relieved"] = 0.9f,
            ["sad"] = 0.85f, ["angry"] = 1.15f, ["scared"] = 1.2f, ["disgusted"] = 0.9f, ["frustrated"] = 1.1f,
            ["lonely"] = 0.85f, ["anxious"] = 1.15f, ["bored"] = 0.8f, ["jealous"] = 1.05f, ["surprised"] = 1.1f,
            ["thinking"] = 0.85f, ["confused"] = 0.9f, ["embarrassed"] = 0.9f, ["nostalgic"] = 0.85f,
            ["dreamy"] = 0.8f, ["determined"] = 1.05f, ["mischievous"] = 1.05f, ["curious"] = 1f, ["melancholic"] = 0.8f,
        };
    }

    /// <summary>Un morceau de ce qui sort réellement : une parole (avec sa position) ou un silence réservé.</summary>
    public readonly struct SpeechSegment
    {
        /// <summary>Texte prononcé (null pour un silence).</summary>
        public readonly string Text;
        /// <summary>Index du premier caractère retenu dans le texte complet (−1 pour un silence).</summary>
        public readonly int Start;
        /// <summary>Durée d'un silence en millisecondes (0 pour une parole).</summary>
        public readonly float SilenceMs;
        /// <summary>Repère prosodique qu'occupe ce silence (<c>sigh</c>, <c>laugh</c>, <c>breath</c>), null pour
        /// une pause ou une parole.</summary>
        public readonly string Cue;

        SpeechSegment(string text, int start, float silenceMs, string cue)
        {
            Text = text; Start = start; SilenceMs = silenceMs; Cue = cue;
        }

        public bool IsSpeech => Text != null;
        public static SpeechSegment Speech(string text, int start) => new SpeechSegment(text, start, 0f, null);
        public static SpeechSegment Silence(float ms, string cue = null) => new SpeechSegment(null, -1, ms, cue);
    }

    /// <summary>
    /// Les repères prosodiques que Mika glisse dans ses répliques et que la voix ne prononce pas :
    /// <c>[PAUSE:300]</c> (ms facultatives, 500 par défaut, bornées à [50, 3000]), <c>[SIGH]</c>,
    /// <c>[LAUGH]</c>, <c>[BREATH]</c>. Portage de <c>TTSService.ts::parseSegments</c> / <c>lipSyncPlan</c>.
    /// </summary>
    public static class SpeechPlan
    {
        /// <summary>
        /// Temps que chaque effet non verbal occupe dans la restitution (<c>TTSService.ts::SFX_DURATION_MS</c>) :
        /// la bouche reste fermée pendant ce temps, et la suite de la phrase ne dérive pas de toute sa durée.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, float> CueDurationMs = new Dictionary<string, float>
        {
            ["sigh"] = 600f, ["laugh"] = 900f, ["breath"] = 350f,
        };

        public const float DefaultPauseMs = 500f;

        static readonly Regex Token = new Regex(@"\[(PAUSE(?::(\d+))?|SIGH|LAUGH|BREATH)\]",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        /// <summary>
        /// Découpe le texte en ce qui est prononcé et en silences réservés. <c>Start</c> d'une parole est l'index
        /// de son premier caractère retenu (blancs de tête ôtés) dans le texte complet : c'est ce qui permet de
        /// recaler la bouche sur une position de lecture rapportée par une vraie voix.
        /// </summary>
        public static List<SpeechSegment> Parse(string text)
        {
            var segments = new List<SpeechSegment>();
            if (string.IsNullOrEmpty(text))
                return segments;

            void PushSpeech(int from, int to)
            {
                string raw = text.Substring(from, to - from);
                string trimmedStart = raw.TrimStart();
                int lead = raw.Length - trimmedStart.Length;
                string chunk = raw.Trim();
                if (chunk.Length > 0)
                    segments.Add(SpeechSegment.Speech(chunk, from + lead));
            }

            int cursor = 0;
            foreach (Match match in Token.Matches(text))
            {
                if (match.Index > cursor)
                    PushSpeech(cursor, match.Index);
                string kind = match.Groups[1].Value.ToUpperInvariant();
                if (kind.StartsWith("PAUSE", StringComparison.Ordinal))
                {
                    float ms = DefaultPauseMs;
                    if (match.Groups[2].Success &&
                        float.TryParse(match.Groups[2].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
                        ms = parsed;
                    segments.Add(SpeechSegment.Silence(Math.Min(3000f, Math.Max(50f, ms))));
                }
                else
                {
                    string cue = kind.ToLowerInvariant();
                    segments.Add(SpeechSegment.Silence(CueDurationMs[cue], cue));
                }
                cursor = match.Index + match.Length;
            }
            if (cursor < text.Length)
                PushSpeech(cursor, text.Length);
            return segments;
        }

        /// <summary>
        /// Les frames de visèmes de toute une réplique : chaque silence réservé par un repère devient une frame
        /// bouche fermée de sa durée exacte (portant le repère), et seuls les caractères prononcés reçoivent du
        /// temps de parole. Les index des frames sont ceux du texte complet.
        /// </summary>
        public static List<VisemeFrame> Frames(string text, float msPerChar)
        {
            var frames = new List<VisemeFrame>();
            foreach (var segment in Parse(text))
            {
                if (segment.IsSpeech)
                    frames.AddRange(FrenchVisemes.Frames(segment.Text, msPerChar, segment.Start));
                else
                    frames.Add(new VisemeFrame { Viseme = Viseme.Sil, Duration = segment.SilenceMs, CharOffset = -1, Cue = segment.Cue });
            }
            return frames;
        }

        /// <summary>Durée totale d'une liste de frames, en secondes.</summary>
        public static float DurationSeconds(IReadOnlyList<VisemeFrame> frames)
        {
            double ms = 0;
            foreach (var f in frames)
                ms += f.Duration;
            return (float)(ms / 1000.0);
        }

        /// <summary>Le texte sans ses repères (pour l'affichage ou une voix qui ne les comprend pas).</summary>
        public static string Strip(string text) =>
            string.IsNullOrEmpty(text) ? text ?? "" : Regex.Replace(Token.Replace(text, " "), @"\s{2,}", " ").Trim();
    }
}
