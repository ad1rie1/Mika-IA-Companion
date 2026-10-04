using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Mika.Avatar
{
    /// <summary>Les temps d'une phrase où le corps et les sourcils ponctuent.</summary>
    public enum BeatKind
    {
        /// <summary>Premier mot d'une proposition : une inspiration rapide, la tête se lève un peu.</summary>
        PhraseStart,
        /// <summary>Un mot plein accentué : un petit hochement.</summary>
        Stress,
        /// <summary>Insistance (intensif, MAJUSCULES, *mot*, exclamation) : un hochement plus marqué et les
        /// sourcils qui se lèvent.</summary>
        Emphasis,
        /// <summary>Virgule, deux-points, point-virgule : la tête se réoriente, une inspiration rapide.</summary>
        Pause,
        /// <summary>« … » — la voix qui s'éteint : une inclinaison douce.</summary>
        Trail,
        /// <summary>Dernier mot d'une question : menton levé, tête inclinée, sourcils tenus hauts.</summary>
        Question,
        /// <summary>Dernier mot d'une affirmation : le hochement qui la clôt.</summary>
        Final,
    }

    public readonly struct SpeechBeat
    {
        /// <summary>Index du caractère dans le texte complet de la réplique.</summary>
        public readonly int At;
        public readonly BeatKind Kind;
        /// <summary>0…1 — met le mouvement à l'échelle.</summary>
        public readonly float Strength;

        public SpeechBeat(int at, BeatKind kind, float strength) { At = at; Kind = kind; Strength = strength; }
        public override string ToString() => $"{Kind}@{At}({Strength:0.00})";
    }

    /// <summary>
    /// Où une phrase se ponctue — analyse du texte seule. Portage de
    /// <c>frontend/src/vtuber/animation/speechBeats.ts</c>.
    /// </summary>
    /// <remarks>
    /// Personne ne parle la tête immobile : la tête plonge sur les mots accentués, les sourcils se lèvent sur
    /// l'insistance, une question finit menton levé, une affirmation se pose d'un hochement. En français
    /// l'accent tombe à la FIN d'un groupe rythmique, et l'accent d'insistance sur les intensifs et les mots en
    /// capitales. La voix ne donne aucune prosodie à lire : les temps sont placés sur le TEXTE et tirés quand le
    /// curseur de parole les atteint. Le visage en tire les sourcils (<see cref="SpeechBrows"/>) ; le reste du
    /// client peut s'abonner à <see cref="MikaFace.BeatReached"/> pour hocher la tête.
    /// </remarks>
    public static class SpeechBeats
    {
        static readonly HashSet<string> Stopwords = new HashSet<string>
        {
            "le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "et", "ou", "mais",
            "donc", "or", "ni", "car", "que", "qu", "qui", "quoi", "je", "j", "tu", "il",
            "elle", "on", "nous", "vous", "ils", "elles", "me", "m", "te", "t", "se", "s",
            "ma", "ta", "sa", "mon", "ton", "son", "mes", "tes", "ses", "notre", "votre",
            "nos", "vos", "leur", "leurs", "ce", "cet", "cette", "ces", "c", "ça", "ca",
            "en", "y", "à", "a", "au", "aux", "dans", "par", "pour", "sur", "avec", "sans",
            "sous", "chez", "ne", "n", "pas", "plus", "est", "es", "suis", "sont", "ai",
            "as", "avait", "était", "être", "avoir", "fait", "faire", "dit", "lui", "moi",
            "toi", "si", "comme", "quand", "alors", "aussi", "bien", "oui", "non", "là",
            "the", "an", "and", "to", "of", "in", "is", "it", "you", "i",
        };

        static readonly HashSet<string> Intensifiers = new HashSet<string>
        {
            "très", "vraiment", "trop", "tellement", "super", "jamais", "absolument",
            "carrément", "grave", "hyper", "énormément", "toujours", "rien", "tout",
            "totalement", "complètement", "franchement", "adore", "déteste", "génial",
            "incroyable", "magnifique", "horrible", "énorme",
        };

        /// <summary>Écart minimal (en caractères) entre deux accents, et l'écart au-delà duquel un mot plein en
        /// reçoit un quoi qu'il arrive (une longue proposition bouge quand même).</summary>
        const int StressGap = 10;
        const int ForceGap = 30;

        static readonly Regex Token = new Regex(@"\[[A-Z_]+(?::[^\]]*)?\]", RegexOptions.CultureInvariant);
        static readonly Regex Sentence = new Regex(@"[^.!?…]+(?:[.!?…]+|$)", RegexOptions.CultureInvariant);
        static readonly Regex WordRe = new Regex(@"\*?[\p{L}\p{N}][\p{L}\p{N}'’-]*\*?", RegexOptions.CultureInvariant);
        static readonly Regex NonLetter = new Regex(@"[^\p{L}]", RegexOptions.CultureInvariant);
        static readonly Regex Elision = new Regex(@"^[dlmtsjcnq][’']", RegexOptions.CultureInvariant);
        static readonly Regex Terminator = new Regex(@"[.!?…]+$", RegexOptions.CultureInvariant);
        static readonly Regex AfterWord = new Regex(@"^\s*([,;:]|\.\.\.|…)?", RegexOptions.CultureInvariant);

        struct Word
        {
            public string Text;
            public int Start;
            /// <summary>Écrit en capitales (≥ 2 lettres) ou entre *astérisques*.</summary>
            public bool Shouted;
        }

        static int Rank(BeatKind kind)
        {
            switch (kind)
            {
                case BeatKind.Question: return 6;
                case BeatKind.Emphasis: return 5;
                case BeatKind.Final: return 4;
                case BeatKind.Trail: return 3;
                case BeatKind.Stress: return 2;
                case BeatKind.Pause: return 1;
                default: return 0;
            }
        }

        public static List<SpeechBeat> Plan(string text)
        {
            var beats = new List<SpeechBeat>();
            if (string.IsNullOrEmpty(text))
                return beats;
            // Les repères que la voix ne dit pas sont masqués par des blancs : les index restent ceux du texte.
            string masked = Token.Replace(text, m => new string(' ', m.Length));
            foreach (Match m in Sentence.Matches(masked))
            {
                if (m.Value.Trim().Length == 0)
                    continue;
                PlanSentence(masked, m.Index, m.Value, beats);
            }
            var sorted = beats
                .Select((b, i) => (b, i))
                .OrderBy(x => x.b.At)
                .ThenByDescending(x => Rank(x.b.Kind))
                .ThenBy(x => x.i)
                .Select(x => x.b)
                .ToList();
            // Un temps par position — le plus fort gagne.
            var result = new List<SpeechBeat>(sorted.Count);
            for (int i = 0; i < sorted.Count; i++)
                if (i == 0 || sorted[i - 1].At != sorted[i].At)
                    result.Add(sorted[i]);
            return result;
        }

        static void PlanSentence(string text, int offset, string sentence, List<SpeechBeat> output)
        {
            var words = new List<Word>();
            foreach (Match w in WordRe.Matches(sentence))
            {
                string raw = w.Value;
                bool starred = raw.Length > 2 && raw.StartsWith("*", StringComparison.Ordinal) && raw.EndsWith("*", StringComparison.Ordinal);
                string clean = raw.Replace("*", "");
                string letters = NonLetter.Replace(clean, "");
                bool shouted = starred || (letters.Length >= 2 && letters == letters.ToUpperInvariant() &&
                                           letters != letters.ToLowerInvariant());
                words.Add(new Word
                {
                    Text = clean,
                    Start = offset + w.Index + (raw.StartsWith("*", StringComparison.Ordinal) ? 1 : 0),
                    Shouted = shouted,
                });
            }
            if (words.Count == 0)
                return;

            var tm = Terminator.Match(sentence.TrimEnd());
            string terminator = tm.Success ? tm.Value : "";
            bool exclaim = terminator.Contains("!");

            output.Add(new SpeechBeat(words[0].Start, BeatKind.PhraseStart, 0.6f));

            int lastBeat = words[0].Start;
            for (int i = 0; i < words.Count; i++)
            {
                var word = words[i];
                string lower = Elision.Replace(word.Text.ToLowerInvariant(), "");
                bool content = !Stopwords.Contains(lower) && lower.Length >= 4;
                int gap = word.Start - lastBeat;

                if (word.Shouted || Intensifiers.Contains(lower))
                {
                    if (gap >= 6 || i == 0)
                    {
                        output.Add(new SpeechBeat(word.Start, BeatKind.Emphasis, word.Shouted ? 1f : 0.8f));
                        lastBeat = word.Start;
                    }
                    continue;
                }

                // Ponctuation de proposition juste après ce mot : il clôt un groupe rythmique — c'est là que le
                // français place l'accent.
                int end = word.Start - offset + word.Text.Length;
                string rest = end <= sentence.Length ? sentence.Substring(end) : "";
                var am = AfterWord.Match(rest);
                string after = am.Groups[1].Success ? am.Groups[1].Value : null;
                if (after == "," || after == ";" || after == ":")
                {
                    if (content && gap >= 6)
                    {
                        output.Add(new SpeechBeat(word.Start, BeatKind.Stress, 0.75f));
                        lastBeat = word.Start;
                    }
                    int at = offset + end + rest.IndexOf(after, StringComparison.Ordinal);
                    output.Add(new SpeechBeat(at, BeatKind.Pause, 0.6f));
                    continue;
                }

                if (content && (gap >= StressGap || (gap >= ForceGap && lower.Length >= 3)))
                {
                    output.Add(new SpeechBeat(word.Start, BeatKind.Stress, Math.Min(1f, 0.45f + lower.Length * 0.05f)));
                    lastBeat = word.Start;
                }
            }

            // Le temps de clôture tombe sur le dernier mot : la tête bouge AVEC lui, pas après que la voix s'est tue.
            var last = words[words.Count - 1];
            BeatKind kind = terminator.Contains("?") ? BeatKind.Question
                : terminator.Contains("…") || terminator.StartsWith("...", StringComparison.Ordinal) ? BeatKind.Trail
                : exclaim ? BeatKind.Emphasis
                : BeatKind.Final;
            // Ce qui est déjà placé à quelques caractères du temps de clôture ne ferait que le brouiller.
            for (int i = output.Count - 1; i >= 0; i--)
            {
                var b = output[i];
                if (b.At >= last.Start - 5 && b.At <= last.Start + last.Text.Length && b.Kind != BeatKind.PhraseStart)
                    output.RemoveAt(i);
            }
            output.Add(new SpeechBeat(last.Start, kind, kind == BeatKind.Emphasis ? 0.9f : 0.8f));
        }
    }

    /// <summary>
    /// Les sourcils de la parole : ils se lèvent sur l'insistance et restent hauts sur une question, puis
    /// retombent (portage de la partie visage de <c>SpeechBodyOverlay.ts</c>). Consomme les temps de
    /// <see cref="SpeechBeats"/> au fil du curseur de parole.
    /// </summary>
    public sealed class SpeechBrows
    {
        static float BrowFor(BeatKind kind)
        {
            switch (kind)
            {
                case BeatKind.PhraseStart: return 0.3f;
                case BeatKind.Stress: return 0.35f;
                case BeatKind.Emphasis: return 1f;
                case BeatKind.Question: return 0.6f;
                case BeatKind.Trail: return 0.25f;
                default: return 0f;
            }
        }

        /// <summary>Un temps que le curseur a dépassé de plus de tant de caractères (un recalage qui saute) est
        /// sauté, pas tiré en retard en rafale.</summary>
        const int StaleChars = 12;
        const float BrowDecay = 3.2f;
        const float QuestionHoldS = 1.3f;
        const float TrailHoldS = 1.2f;

        List<SpeechBeat> _beats = new List<SpeechBeat>();
        int _next;
        int _lastCursor = -1;
        float _holdRemaining;
        BeatKind? _holdKind;

        public float Emphasis { get; private set; }
        public float Question { get; private set; }

        /// <summary>Une nouvelle réplique commence : ses temps remplacent ce qui restait.</summary>
        public void Begin(List<SpeechBeat> beats)
        {
            _beats = beats ?? new List<SpeechBeat>();
            _next = 0;
            _lastCursor = -1;
        }

        /// <summary>« Bien reçu » : le petit haussement de sourcils de qui reçoit un message.</summary>
        public void Acknowledge() => Emphasis = Math.Max(Emphasis, 0.35f);

        /// <param name="fired">Reçoit les temps atteints à ce pas (pour l'événement public).</param>
        /// <param name="scale">Échelle des mouvements (un murmure à soi-même ponctue à peine).</param>
        public void Step(float dt, int cursor, bool speaking, float scale, List<SpeechBeat> fired)
        {
            if (!(dt > 0f))
                dt = 0f;
            if (speaking)
                Consume(cursor, scale, fired);
            if (_holdRemaining > 0f)
            {
                _holdRemaining -= dt;
                if (_holdRemaining <= 0f)
                    _holdKind = null;
            }
            float questionTarget = _holdKind == BeatKind.Question ? 1f : 0f;
            Question += (questionTarget - Question) * Math.Min(1f, dt * 5f);
            Emphasis = Math.Max(0f, Emphasis - dt * BrowDecay * Math.Max(0.2f, Emphasis));
        }

        void Consume(int cursor, float scale, List<SpeechBeat> fired)
        {
            if (cursor < 0 || _beats.Count == 0)
                return;
            if (cursor < _lastCursor - 3)
            {
                // La voix a recalé le curseur en arrière : on réarme à partir de là.
                _next = _beats.FindIndex(b => b.At >= cursor);
                if (_next < 0)
                    _next = _beats.Count;
            }
            _lastCursor = cursor;
            while (_next < _beats.Count && _beats[_next].At <= cursor)
            {
                var beat = _beats[_next++];
                if (cursor - beat.At > StaleChars)
                    continue;
                float s = beat.Strength * scale;
                Emphasis = Math.Min(1f, Math.Max(Emphasis, BrowFor(beat.Kind) * s));
                switch (beat.Kind)
                {
                    case BeatKind.Question:
                        _holdKind = BeatKind.Question;
                        _holdRemaining = QuestionHoldS;
                        break;
                    case BeatKind.Trail:
                        _holdKind = BeatKind.Trail;
                        _holdRemaining = TrailHoldS;
                        break;
                    case BeatKind.Final:
                        _holdKind = null;
                        _holdRemaining = 0f;
                        break;
                }
                fired?.Add(beat);
            }
        }
    }
}
