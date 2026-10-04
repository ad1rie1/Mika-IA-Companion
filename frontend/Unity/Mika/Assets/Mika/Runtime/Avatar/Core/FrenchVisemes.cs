using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Mika.Avatar
{
    /// <summary>Les 15 visèmes VRChat/Oculus, dans l'ordre de leurs morphs <c>vrc.v_*</c>.</summary>
    public enum Viseme
    {
        Sil = 0, PP, FF, TH, DD, KK, CH, SS, NN, RR, AA, E, IH, OH, OU,
    }

    /// <summary>
    /// Inventaire phonétique réduit, en notation proche du X-SAMPA (<see cref="FrenchVisemes.Symbol"/>) :
    /// schwa « @ », « eu » « 2 », « è » « E », nasales « ~ », « gn » « J », « ch »/« j » « S »/« Z », le « u » de
    /// « nuit » « H », le r français « R ».
    /// </summary>
    public enum Phoneme
    {
        A, AN, Ee, Eh, EN, Schwa, Eu, I, O, ON, U, Y,
        Yod, W, Hu,
        P, B, M, F, V, T, D, N, L, Gn,
        K, G, S, Z, Ch, Zh, R,
    }

    public readonly struct PhonemeToken
    {
        public readonly Phoneme Ph;
        /// <summary>Index, dans le texte analysé, du premier caractère de son graphème.</summary>
        public readonly int At;
        public PhonemeToken(Phoneme ph, int at) { Ph = ph; At = at; }
        public override string ToString() => FrenchVisemes.Symbol(Ph) + "@" + At;
    }

    public struct VisemeFrame
    {
        public Viseme Viseme;
        /// <summary>Poids crête du visème (0 pour <c>Sil</c>).</summary>
        public float Weight;
        /// <summary>Durée en millisecondes.</summary>
        public float Duration;
        /// <summary>Index, dans le texte complet de la réplique, du caractère que cette frame articule ; −1 pour
        /// un silence ou un plan sans position.</summary>
        public int CharOffset;
        /// <summary>Blanc entre deux mots : pas de fermeture, la bouche glisse d'une forme à la suivante.</summary>
        public bool Gap;
        /// <summary>Repère prosodique (<c>sigh</c>, <c>laugh</c>, <c>breath</c>) que porte ce silence, ou null.</summary>
        public string Cue;
    }

    /// <summary>
    /// Texte français → visèmes, pour une bouche qui articule. Portage fidèle de
    /// <c>frontend/Web/src/audio/frenchVisemes.ts</c> (mêmes règles, mêmes cas de test).
    /// </summary>
    /// <remarks>
    /// Un passage graphème → phonème raisonnable (digraphes, nasales, lettres muettes, élisions, nombres en
    /// toutes lettres), puis chaque phonème projeté sur les 15 visèmes. Ce n'est pas un phonétiseur de
    /// linguiste : il doit avoir l'air juste sur un visage à vitesse de parole. Deux invariants que le lip-sync
    /// exige : chaque frame garde l'index d'ORIGINE du caractère qu'elle articule (le recalage sur une position
    /// de lecture en dépend), et la durée totale d'un segment vaut <c>msPerChar × SpokenLength(texte)</c> —
    /// blancs repliés, et un nombre compté à la longueur de sa forme dite (« 2026 » dure « deux mille
    /// vingt-six »).
    /// </remarks>
    public static class FrenchVisemes
    {
        public static readonly IReadOnlyList<Viseme> All = (Viseme[])Enum.GetValues(typeof(Viseme));

        /// <summary>Nom du visème comme le web l'écrit (<c>sil</c>, <c>PP</c>, <c>kk</c>, <c>aa</c>…).</summary>
        public static string Name(Viseme v)
        {
            switch (v)
            {
                case Viseme.Sil: return "sil";
                case Viseme.KK: return "kk";
                case Viseme.NN: return "nn";
                case Viseme.AA: return "aa";
                case Viseme.IH: return "ih";
                case Viseme.OH: return "oh";
                case Viseme.OU: return "ou";
                default: return v.ToString();
            }
        }

        /// <summary>Morph VRChat d'un visème : <c>vrc.v_aa</c>, <c>vrc.v_pp</c>…</summary>
        public static string VrcMorph(Viseme v) => "vrc.v_" + Name(v).ToLowerInvariant();

        static readonly string[] Symbols =
        {
            "a", "a~", "e", "E", "e~", "@", "2", "i", "o", "o~", "u", "y",
            "j", "w", "H",
            "p", "b", "m", "f", "v", "t", "d", "n", "l", "J",
            "k", "g", "s", "z", "S", "Z", "R",
        };

        static readonly Dictionary<string, Phoneme> BySymbol = Enumerable.Range(0, Symbols.Length)
            .ToDictionary(i => Symbols[i], i => (Phoneme)i, StringComparer.Ordinal);

        public static string Symbol(Phoneme p) => Symbols[(int)p];

        public readonly struct PhonemeInfo
        {
            public readonly Viseme Viseme;
            /// <summary>Amplitude crête du visème.</summary>
            public readonly float Weight;
            /// <summary>Durée relative : les voyelles tiennent, les consonnes passent.</summary>
            public readonly float Length;
            public readonly bool Vowel;
            public PhonemeInfo(Viseme v, float w, float l, bool vowel = false) { Viseme = v; Weight = w; Length = l; Vowel = vowel; }
        }

        static readonly PhonemeInfo[] Infos =
        {
            new PhonemeInfo(Viseme.AA, 1.0f, 1.0f, true),   // a
            new PhonemeInfo(Viseme.AA, 0.75f, 1.15f, true), // a~
            new PhonemeInfo(Viseme.E, 0.8f, 0.95f, true),   // e
            new PhonemeInfo(Viseme.E, 0.85f, 1.0f, true),   // E
            new PhonemeInfo(Viseme.E, 0.7f, 1.15f, true),   // e~
            // Le schwa français est arrondi et bref (« le » ≈ [lø]).
            new PhonemeInfo(Viseme.OH, 0.4f, 0.6f, true),   // @
            new PhonemeInfo(Viseme.OH, 0.6f, 1.0f, true),   // 2
            new PhonemeInfo(Viseme.IH, 0.8f, 0.9f, true),   // i
            new PhonemeInfo(Viseme.OH, 0.9f, 1.0f, true),   // o
            new PhonemeInfo(Viseme.OH, 0.8f, 1.15f, true),  // o~
            new PhonemeInfo(Viseme.OU, 0.9f, 0.95f, true),  // u
            // [y] : lèvres arrondies et serrées, la même bouche que « ou » vue de face.
            new PhonemeInfo(Viseme.OU, 0.85f, 0.9f, true),  // y
            new PhonemeInfo(Viseme.IH, 0.5f, 0.4f),         // j
            new PhonemeInfo(Viseme.OU, 0.7f, 0.45f),        // w
            new PhonemeInfo(Viseme.OU, 0.6f, 0.4f),         // H
            // Bilabiales : les lèvres se ferment, poids plein.
            new PhonemeInfo(Viseme.PP, 1.0f, 0.55f),        // p
            new PhonemeInfo(Viseme.PP, 1.0f, 0.55f),        // b
            new PhonemeInfo(Viseme.PP, 1.0f, 0.6f),         // m
            // Labiodentales : lèvre inférieure sous les incisives.
            new PhonemeInfo(Viseme.FF, 1.0f, 0.65f),        // f
            new PhonemeInfo(Viseme.FF, 0.95f, 0.6f),        // v
            new PhonemeInfo(Viseme.DD, 0.85f, 0.5f),        // t
            new PhonemeInfo(Viseme.DD, 0.85f, 0.5f),        // d
            new PhonemeInfo(Viseme.NN, 0.85f, 0.55f),       // n
            new PhonemeInfo(Viseme.NN, 0.75f, 0.5f),        // l
            new PhonemeInfo(Viseme.NN, 0.9f, 0.6f),         // J
            new PhonemeInfo(Viseme.KK, 0.85f, 0.55f),       // k
            new PhonemeInfo(Viseme.KK, 0.8f, 0.55f),        // g
            new PhonemeInfo(Viseme.SS, 0.95f, 0.65f),       // s
            new PhonemeInfo(Viseme.SS, 0.9f, 0.6f),         // z
            new PhonemeInfo(Viseme.CH, 1.0f, 0.65f),        // S
            new PhonemeInfo(Viseme.CH, 0.95f, 0.6f),        // Z
            // Le r uvulaire ne se voit presque pas sur les lèvres.
            new PhonemeInfo(Viseme.RR, 0.7f, 0.5f),         // R
        };

        public static PhonemeInfo Info(Phoneme p) => Infos[(int)p];

        // ── Timing ──────────────────────────────────────────────────────────

        /// <summary>Part d'un caractère qu'un blanc garde pour lui : assez pour une détente, trop peu pour une fermeture.</summary>
        const float SpaceGapShare = 0.5f;
        /// <summary>Allongement de la dernière voyelle avant une pause : l'accent français tombe en fin de groupe.</summary>
        const float FinalLengthening = 1.35f;
        /// <summary>Variation d'amplitude déterministe d'une voyelle à l'autre (±4 %) : sans elle, deux « a »
        /// successifs sont deux copies — c'est ce qui fait robot.</summary>
        const float WeightJitter = 0.08f;

        // ── Classes de lettres ──────────────────────────────────────────────

        const string VowelLetters = "aàâäeéèêëiîïoôöuùûüyÿœæ";
        const string FrontLetters = "eéèêëiîïyÿ"; // c et g doux devant elles
        const string SilentFinals = "stdxzp";
        const string Joiners = "'’ʼ-‐‑";
        const string Apostrophes = "'’ʼ";
        /// <summary>Ponctuation qui pose une vraie pause (fermeture). Guillemets, parenthèses ou émojis ne se
        /// disent pas : ils glissent, comme un blanc.</summary>
        const string PausePunct = ".,;:!?…—–";

        static bool InSet(char c, string set) => c != '\0' && set.IndexOf(c) >= 0;
        static bool IsVowelLetter(char c) => InSet(c, VowelLetters);
        static bool IsLetter(char c) => char.IsLetter(c);
        static bool IsMark(char c)
        {
            var cat = CharUnicodeInfo.GetUnicodeCategory(c);
            return cat == UnicodeCategory.NonSpacingMark || cat == UnicodeCategory.SpacingCombiningMark ||
                   cat == UnicodeCategory.EnclosingMark;
        }
        static bool IsSpace(char c) => char.IsWhiteSpace(c);
        static bool IsDigit(char c) => c >= '0' && c <= '9';
        static bool IsJoiner(char c) => Joiners.IndexOf(c) >= 0;
        static bool IsApostrophe(char c) => Apostrophes.IndexOf(c) >= 0;

        // ── Lexique : ce que les règles ne savent pas deviner ───────────────

        /// <summary>Mots entiers irréguliers (phonèmes séparés par des espaces).</summary>
        static readonly Dictionary<string, string> Exceptions = new Dictionary<string, string>
        {
            ["est"] = "E", ["et"] = "e", ["es"] = "E", ["ok"] = "o k e",
            ["vingt"] = "v e~", ["vingts"] = "v e~", ["sept"] = "s E t", ["huit"] = "H i t", ["six"] = "s i s",
            ["dix"] = "d i s", ["soixante"] = "s w a s a~ t", ["fils"] = "f i s", ["femme"] = "f a m",
            ["femmes"] = "f a m", ["monsieur"] = "m @ s j 2", ["messieurs"] = "m e s j 2", ["oignon"] = "o J o~",
            ["second"] = "s @ g o~", ["seconde"] = "s @ g o~ d", ["eu"] = "y", ["eus"] = "y", ["eut"] = "y",
            ["pays"] = "p E i", ["août"] = "u t", ["ouest"] = "w E s t", ["œil"] = "2 j", ["yeux"] = "j 2",
            ["gens"] = "Z a~", ["chez"] = "S e", ["clef"] = "k l e", ["doigt"] = "d w a", ["doigts"] = "d w a",
            ["corps"] = "k o R", ["blanc"] = "b l a~", ["franc"] = "f R a~", ["tabac"] = "t a b a",
            ["estomac"] = "E s t o m a", ["porc"] = "p o R", ["hier"] = "j E R", ["fier"] = "f j E R",
            ["cher"] = "S E R", ["hiver"] = "i v E R", ["super"] = "s y p E R", ["enfer"] = "a~ f E R",
            ["amer"] = "a m E R",
        };

        /// <summary>Mots dont la consonne finale se prononce malgré la règle des muettes.</summary>
        static readonly HashSet<string> FinalKept = new HashSet<string>
        {
            "bus", "os", "ours", "mars", "sens", "virus", "bonus", "tennis", "hélas", "maïs",
            "jadis", "oasis", "iris", "atlas", "cactus", "campus", "lys", "autobus",
            "net", "but", "test", "brut", "chut", "dot", "kit", "mat", "sud",
            "stop", "top", "cap", "slip", "clip", "hip",
            "gaz", "fax", "box", "max", "relax", "lynx", "index", "linux", "sphinx",
        };

        /// <summary>« -er » final prononcé [ɛʁ] (le cas général est l'infinitif muet).</summary>
        static readonly HashSet<string> ErKept = new HashSet<string>
        {
            "laser", "cancer", "hamster", "poster", "master", "starter", "leader",
        };

        /// <summary>« -ent » final qui n'est pas une terminaison verbale.</summary>
        static readonly HashSet<string> EntPronounced = new HashSet<string>
        {
            "parent", "souvent", "absent", "présent", "argent", "agent", "urgent", "client",
            "patient", "impatient", "talent", "accent", "content", "serpent", "évident",
            "différent", "intelligent", "prudent", "récent", "fréquent", "excellent",
            "innocent", "adolescent", "accident", "incident", "président", "résident",
            "équivalent", "violent", "ardent", "torrent", "orient", "occident", "quotient",
            "permanent", "compétent", "décent", "indécent", "pertinent", "continent",
        };

        /// <summary>Sujets qui rendent un « -ent » final muet à coup sûr (« ils mangent »).</summary>
        static readonly HashSet<string> PluralSubjects = new HashSet<string> { "ils", "elles" };

        /// <summary>Monosyllabes où le « e » final se dit (schwa).</summary>
        static readonly HashSet<string> SchwaWords = new HashSet<string> { "que" };

        /// <summary>« ill » qui se dit [il] et non [ij].</summary>
        static readonly Regex LlPronounced = new Regex("^(vill|mill|tranquill|lill|distill|oscill|pupill|bacill)",
            RegexOptions.CultureInvariant);

        /// <summary>Consonne élidée devant une apostrophe (« l'ami », « c'est », « j'ai »).</summary>
        static readonly Dictionary<char, Phoneme> ElidedLetter = new Dictionary<char, Phoneme>
        {
            ['l'] = Phoneme.L, ['d'] = Phoneme.D, ['j'] = Phoneme.Zh, ['m'] = Phoneme.M, ['n'] = Phoneme.N,
            ['s'] = Phoneme.S, ['t'] = Phoneme.T, ['c'] = Phoneme.S, ['ç'] = Phoneme.S,
        };

        /// <summary>Une lettre isolée se dit par son nom (« le point b ») ; « y » et « a » sont des mots.</summary>
        static readonly Dictionary<char, string> LetterNames = new Dictionary<char, string>
        {
            ['a'] = "a", ['à'] = "a", ['â'] = "a", ['e'] = "@", ['é'] = "e", ['è'] = "E", ['ê'] = "E", ['i'] = "i",
            ['î'] = "i", ['o'] = "o", ['ô'] = "o", ['u'] = "y", ['y'] = "i",
            ['b'] = "b e", ['c'] = "s e", ['ç'] = "s e", ['d'] = "d e", ['f'] = "E f", ['g'] = "Z e", ['h'] = "a S",
            ['j'] = "Z i", ['k'] = "k a", ['l'] = "E l", ['m'] = "E m", ['n'] = "E n", ['p'] = "p e", ['q'] = "k y",
            ['r'] = "E R", ['s'] = "E s", ['t'] = "t e", ['v'] = "v e", ['w'] = "d u b l @ v e", ['x'] = "i k s",
            ['z'] = "z E d",
        };

        static string LetterName(char c) => LetterNames.TryGetValue(c, out var n) ? n : "@";

        // ── Mots ────────────────────────────────────────────────────────────

        /// <summary>Répartit une chaîne de phonèmes sur les lettres d'un mot, en ordre.</summary>
        static void Spread(string phonemes, IReadOnlyList<int> pos, List<PhonemeToken> output)
        {
            var parts = phonemes.Split(' ');
            int L = pos.Count;
            for (int k = 0; k < parts.Length; k++)
                output.Add(new PhonemeToken(BySymbol[parts[k]], pos[Math.Min(L - 1, (int)Math.Floor((double)k * L / parts.Length))]));
        }

        /// <summary>
        /// Longueur prononcée d'un mot : ce qui suit est muet (e muet, « -es », « -ent » verbal, consonnes
        /// finales, r de l'infinitif). Les lettres muettes restent lisibles par les règles comme contexte.
        /// </summary>
        static int PronouncedEnd(string s, string prev)
        {
            int L = s.Length;
            if (L <= 1)
                return L;
            if (s.EndsWith("aient", StringComparison.Ordinal))
                return L - 3; // imparfait : « étaient »
            if (s.EndsWith("ent", StringComparison.Ordinal) && L >= 4)
            {
                if (PluralSubjects.Contains(prev))
                    return L - 3;
                if (L >= 5 && !s.EndsWith("ment", StringComparison.Ordinal) && !EntPronounced.Contains(s) &&
                    !s.EndsWith("tient", StringComparison.Ordinal) && !s.EndsWith("vient", StringComparison.Ordinal))
                    return L - 3;
            }
            int end = L;
            if (s.EndsWith("es", StringComparison.Ordinal) && L > 3 && !FinalKept.Contains(s))
                end = L - 2; // pluriel ou 2e personne d'un mot en e muet
            else if (s.EndsWith("e", StringComparison.Ordinal))
            {
                if (L > 2 && !SchwaWords.Contains(s))
                    end = L - 1; // e muet
            }
            else if (!FinalKept.Contains(s) && !s.EndsWith("ss", StringComparison.Ordinal) && InSet(s[L - 1], SilentFinals))
            {
                char first = s[L - 1];
                end = L - 1;
                // « grands », « temps », « petits » : le pluriel découvre une autre muette.
                if ((first == 's' || first == 'x') && end > 1 && InSet(s[end - 1], "tdp"))
                    end -= 1;
            }
            string b = s.Substring(0, end);
            if (b.EndsWith("er", StringComparison.Ordinal) && end >= 4 && !ErKept.Contains(b))
                end -= 1; // infinitif, -ier
            else if (b.EndsWith("ng", StringComparison.Ordinal))
                end -= 1; // « long », « sang »
            return end;
        }

        /// <summary>
        /// Phonétise un mot sans apostrophe ni trait d'union. <paramref name="s"/> est en minuscules composées,
        /// <c>pos[i]</c> l'index source de la lettre <c>s[i]</c>.
        /// </summary>
        static void PronounceWord(string s, string orig, IReadOnlyList<int> pos, string prev, bool elided,
            List<PhonemeToken> output)
        {
            int L = s.Length;
            if (L == 0)
                return;

            if (elided && L == 1)
            {
                if (ElidedLetter.TryGetValue(s[0], out var ph))
                    output.Add(new PhonemeToken(ph, pos[0]));
                else
                    Spread(LetterName(s[0]), pos, output);
                return;
            }
            if (!elided)
            {
                if (Exceptions.TryGetValue(s, out var exception))
                {
                    Spread(exception, pos, output);
                    return;
                }
                if (L == 1)
                {
                    Spread(LetterName(s[0]), pos, output);
                    return;
                }
                // Sigle sans voyelle (« SMS ») : la voix l'épelle.
                if (orig == orig.ToUpperInvariant() && orig != orig.ToLowerInvariant() && !s.Any(IsVowelLetter))
                {
                    for (int k = 0; k < L; k++)
                        Spread(LetterName(s[k]), new[] { pos[k] }, output);
                    return;
                }
            }

            int end = elided ? L : PronouncedEnd(s, prev);
            int start = output.Count;
            char Ch(int k) => k >= 0 && k < L ? s[k] : '\0';
            bool V(int k) => IsVowelLetter(Ch(k));
            bool C(int k) => Ch(k) != '\0' && !IsVowelLetter(Ch(k));
            void Emit(Phoneme ph, int k) => output.Add(new PhonemeToken(ph, pos[Math.Min(k, L - 1)]));
            // Un n/m nasalise la voyelle qui le précède s'il n'est suivi ni d'une voyelle — même muette :
            // « une », « bonne » — ni d'un n/m/h.
            bool Nasal(int k) => InSet(Ch(k), "nm") && k < end && !V(k + 1) && !InSet(Ch(k + 1), "nmh");
            // Consonne simple ; une consonne doublée ne se dit qu'une fois.
            int Doubled(int k, Phoneme ph)
            {
                Emit(ph, k);
                return Ch(k + 1) == s[k] ? 2 : 1;
            }
            // Le « e » sans accent ni digraphe : [e], [ɛ], schwa, ou rien.
            void PlainE(int k)
            {
                if (k == end - 1)
                {
                    if (end < L)
                        Emit(InSet(Ch(k + 1), "rzds") ? Phoneme.Ee : Phoneme.Eh, k); // « manger », « chez », « les » / « poulet »
                    else
                        Emit(Phoneme.Schwa, k); // « le », « que »
                    return;
                }
                if (k == 0)
                {
                    Emit(Phoneme.Eh, k); // « elle », « Eric »
                    return;
                }
                if (!C(k + 1))
                {
                    Emit(Phoneme.Eh, k);
                    return;
                }
                // Une consonne (un digraphe compte pour une) puis une voyelle : syllabe ouverte, schwa ; deux
                // consonnes ou une finale : syllabe fermée, [ɛ].
                string pair = new string(new[] { Ch(k + 1), Ch(k + 2) });
                int after = k + (pair == "ch" || pair == "ph" || pair == "th" || pair == "gn" ? 3 : 2);
                bool cluster = InSet(Ch(k + 1), "bcdfgkptv") && InSet(Ch(k + 2), "lr") && V(k + 3);
                bool closed = !cluster && (C(after) || after >= end);
                if (closed)
                {
                    Emit(Phoneme.Eh, k);
                    return;
                }
                // Schwa entre une seule consonne et une consonne + voyelle : il tombe (« samedi » [samdi]).
                int n = output.Count - start;
                bool elidable = n >= 2 && !Info(output[output.Count - 1].Ph).Vowel &&
                                Info(output[output.Count - 2].Ph).Vowel && C(k + 1) && V(k + 2);
                if (!elidable)
                    Emit(Phoneme.Schwa, k);
            }

            int i = 0;
            while (i < end)
            {
                char c = s[i];
                switch (c)
                {
                    case 'a':
                    case 'à':
                    case 'â':
                    case 'ä':
                        if (c == 'a' && Ch(i + 1) == 'i' && Ch(i + 2) == 'l' && (i + 3 >= end || Ch(i + 3) == 'l'))
                        {
                            Emit(Phoneme.A, i); // « travail », « paille »
                            Emit(Phoneme.Yod, i + 1);
                            i += Ch(i + 3) == 'l' ? 4 : 3;
                        }
                        else if (c == 'a' && InSet(Ch(i + 1), "iî"))
                        {
                            if (Nasal(i + 2))
                            {
                                Emit(Phoneme.EN, i); // « pain », « faim »
                                i += 3;
                            }
                            else
                            {
                                Emit(Phoneme.Eh, i);
                                i += 2;
                            }
                        }
                        else if (c == 'a' && InSet(Ch(i + 1), "uû"))
                        {
                            Emit(Phoneme.O, i);
                            i += 2;
                        }
                        else if (c == 'a' && Ch(i + 1) == 'y')
                        {
                            Emit(Phoneme.Eh, i); // « crayon » : le y suit en [j]
                            i += 1;
                        }
                        else if (Nasal(i + 1))
                        {
                            Emit(Phoneme.AN, i);
                            i += 2;
                        }
                        else
                        {
                            Emit(Phoneme.A, i);
                            i += 1;
                        }
                        break;
                    case 'e':
                        if (Ch(i + 1) == 'a' && Ch(i + 2) == 'u')
                        {
                            Emit(Phoneme.O, i); // « eau », « oiseau »
                            i += 3;
                        }
                        else if (Ch(i + 1) == 'u' && Ch(i + 2) == 'i' && Ch(i + 3) == 'l')
                        {
                            Emit(Phoneme.Eu, i); // « feuille », « fauteuil »
                            Emit(Phoneme.Yod, i + 2);
                            i += Ch(i + 4) == 'l' ? 5 : 4;
                        }
                        else if (InSet(Ch(i + 1), "uû"))
                        {
                            Emit(Phoneme.Eu, i);
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'i' && Ch(i + 2) == 'l' && (i + 3 >= end || Ch(i + 3) == 'l'))
                        {
                            Emit(Phoneme.Eh, i); // « soleil », « abeille »
                            Emit(Phoneme.Yod, i + 1);
                            i += Ch(i + 3) == 'l' ? 4 : 3;
                        }
                        else if (InSet(Ch(i + 1), "iî"))
                        {
                            if (Nasal(i + 2))
                            {
                                Emit(Phoneme.EN, i); // « plein »
                                i += 3;
                            }
                            else
                            {
                                Emit(Phoneme.Eh, i);
                                i += 2;
                            }
                        }
                        else if (Ch(i + 1) == 'y')
                        {
                            Emit(Phoneme.Eh, i);
                            i += 1;
                        }
                        else if (Nasal(i + 1))
                        {
                            // « bien », « européen », « viendra » : [ɛ̃] après i/é/y en fin de mot ou devant d ;
                            // « science », « patience », et partout ailleurs : [ɑ̃].
                            bool ien = InSet(Ch(i - 1), "iéy") && (i + 2 >= end || Ch(i + 2) == 'd');
                            Emit(ien ? Phoneme.EN : Phoneme.AN, i);
                            i += 2;
                        }
                        else
                        {
                            PlainE(i);
                            i += 1;
                        }
                        break;
                    case 'é':
                    case 'æ':
                        Emit(Phoneme.Ee, i);
                        i += 1;
                        break;
                    case 'è':
                    case 'ê':
                    case 'ë':
                        Emit(Phoneme.Eh, i);
                        i += 1;
                        break;
                    case 'i':
                    case 'î':
                    case 'ï':
                    case 'y':
                    case 'ÿ':
                    {
                        bool isY = c == 'y' || c == 'ÿ';
                        if (isY && ((i == 0 && V(i + 1)) || (V(i - 1) && V(i + 1))))
                        {
                            Emit(Phoneme.Yod, i); // « yaourt », « crayon », « voyage »
                            i += 1;
                        }
                        else if (c == 'i' && i > 0 && Ch(i + 1) == 'l' && Ch(i + 2) == 'l')
                        {
                            if (LlPronounced.IsMatch(s))
                            {
                                Emit(Phoneme.I, i); // « ville », « million » : le « ll » suit en [l]
                                i += 1;
                            }
                            else
                            {
                                Emit(Phoneme.I, i); // « fille », « famille »
                                Emit(Phoneme.Yod, i + 1);
                                i += 3;
                            }
                        }
                        else if ((c == 'i' || isY) && Nasal(i + 1))
                        {
                            Emit(Phoneme.EN, i);
                            i += 2;
                        }
                        else if (c == 'i' && i > 0 && C(i - 1) && V(i + 1) && i + 1 < end)
                        {
                            Emit(Phoneme.Yod, i); // « pied », « bien », « nation »
                            i += 1;
                        }
                        else
                        {
                            Emit(Phoneme.I, i);
                            i += 1;
                        }
                        break;
                    }
                    case 'o':
                    case 'ô':
                    case 'ö':
                        if (c == 'o' && Ch(i + 1) == 'i' && Nasal(i + 2))
                        {
                            Emit(Phoneme.W, i); // « loin », « point »
                            Emit(Phoneme.EN, i + 1);
                            i += 3;
                        }
                        else if (c == 'o' && InSet(Ch(i + 1), "iî"))
                        {
                            Emit(Phoneme.W, i); // « moi », « oiseau »
                            Emit(Phoneme.A, i + 1);
                            i += 2;
                        }
                        else if (c == 'o' && Ch(i + 1) == 'y')
                        {
                            Emit(Phoneme.W, i); // « voyage » : le y suit en [j]
                            Emit(Phoneme.A, i);
                            i += 1;
                        }
                        else if (c == 'o' && InSet(Ch(i + 1), "uùû"))
                        {
                            if (Ch(i + 2) == 'i' && Ch(i + 3) == 'l' && Ch(i + 4) == 'l')
                            {
                                Emit(Phoneme.U, i); // « grenouille »
                                Emit(Phoneme.Yod, i + 2);
                                i += 5;
                            }
                            else if (V(i + 2) && i + 2 < end)
                            {
                                Emit(Phoneme.W, i); // « oui », « jouer »
                                i += 2;
                            }
                            else
                            {
                                Emit(Phoneme.U, i);
                                i += 2;
                            }
                        }
                        else if (Nasal(i + 1))
                        {
                            Emit(Phoneme.ON, i);
                            i += 2;
                        }
                        else
                        {
                            Emit(Phoneme.O, i);
                            i += 1;
                        }
                        break;
                    case 'œ':
                        Emit(Phoneme.Eu, i); // « cœur », « œuvre »
                        i += Ch(i + 1) == 'u' ? 2 : 1;
                        break;
                    case 'u':
                    case 'ù':
                    case 'û':
                    case 'ü':
                        if (c == 'u' && Ch(i + 1) == 'e' && Ch(i + 2) == 'i' && Ch(i + 3) == 'l')
                        {
                            Emit(Phoneme.Eu, i); // « accueil », « cueillir »
                            Emit(Phoneme.Yod, i + 2);
                            i += Ch(i + 4) == 'l' ? 5 : 4;
                        }
                        else if (c == 'u' && Ch(i + 1) == 'm' && i + 2 >= L)
                        {
                            Emit(Phoneme.O, i); // « album », « maximum »
                            Emit(Phoneme.M, i + 1);
                            i += 2;
                        }
                        else if (c == 'u' && Nasal(i + 1))
                        {
                            Emit(Phoneme.EN, i); // « un », « lundi »
                            i += 2;
                        }
                        else if (i > 0 && V(i + 1) && i + 1 < end)
                        {
                            Emit(Phoneme.Hu, i); // « nuit », « lui »
                            i += 1;
                        }
                        else
                        {
                            Emit(Phoneme.Y, i);
                            i += 1;
                        }
                        break;
                    case 'c':
                        if (Ch(i + 1) == 'h')
                        {
                            Emit(InSet(Ch(i + 2), "rl") ? Phoneme.K : Phoneme.Ch, i); // « chat » / « chrome »
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'c')
                        {
                            Emit(Phoneme.K, i);
                            if (InSet(Ch(i + 2), FrontLetters))
                                Emit(Phoneme.S, i + 1); // « accent »
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'k')
                        {
                            Emit(Phoneme.K, i);
                            i += 2;
                        }
                        else
                        {
                            Emit(InSet(Ch(i + 1), FrontLetters) ? Phoneme.S : Phoneme.K, i);
                            i += 1;
                        }
                        break;
                    case 'ç':
                        Emit(Phoneme.S, i);
                        i += 1;
                        break;
                    case 'g':
                        if (Ch(i + 1) == 'n')
                        {
                            Emit(Phoneme.Gn, i); // « champagne »
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'u' && InSet(Ch(i + 2), FrontLetters))
                        {
                            Emit(Phoneme.G, i); // « guitare »
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'e' && InSet(Ch(i + 2), "aâoôu"))
                        {
                            Emit(Phoneme.Zh, i); // « mangeons », « geai »
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'g')
                        {
                            Emit(Phoneme.G, i);
                            if (InSet(Ch(i + 2), FrontLetters))
                                Emit(Phoneme.Zh, i + 1); // « suggérer »
                            i += 2;
                        }
                        else
                        {
                            Emit(InSet(Ch(i + 1), FrontLetters) ? Phoneme.Zh : Phoneme.G, i);
                            i += 1;
                        }
                        break;
                    case 'h':
                        i += 1; // muet hors digraphes
                        break;
                    case 'j':
                        Emit(Phoneme.Zh, i);
                        i += 1;
                        break;
                    case 'p':
                        if (Ch(i + 1) == 'h')
                        {
                            Emit(Phoneme.F, i); // « photo »
                            i += 2;
                        }
                        else
                            i += Doubled(i, Phoneme.P);
                        break;
                    case 'q':
                        Emit(Phoneme.K, i); // « qu » : le u ne se dit pas
                        i += Ch(i + 1) == 'u' ? 2 : 1;
                        break;
                    case 's':
                        if (Ch(i + 1) == 'c' && Ch(i + 2) == 'h')
                        {
                            Emit(Phoneme.Ch, i);
                            i += 3;
                        }
                        else if (Ch(i + 1) == 'h')
                        {
                            Emit(Phoneme.Ch, i);
                            i += 2;
                        }
                        else if (Ch(i + 1) == 's')
                        {
                            Emit(Phoneme.S, i);
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'c' && InSet(Ch(i + 2), FrontLetters))
                        {
                            Emit(Phoneme.S, i); // « science »
                            i += 2;
                        }
                        else
                        {
                            Emit(V(i - 1) && V(i + 1) ? Phoneme.Z : Phoneme.S, i); // « oiseau », « chose »
                            i += 1;
                        }
                        break;
                    case 't':
                        if (Ch(i + 1) == 'h' || Ch(i + 1) == 't')
                        {
                            Emit(Phoneme.T, i);
                            i += 2;
                        }
                        else if (Ch(i + 1) == 'i' && Ch(i + 2) == 'o' && Ch(i + 3) == 'n' && i > 0 && !InSet(Ch(i - 1), "sx"))
                        {
                            Emit(Phoneme.S, i); // « nation », mais « question »
                            i += 1;
                        }
                        else
                        {
                            Emit(Phoneme.T, i);
                            i += 1;
                        }
                        break;
                    case 'x':
                        if (i == 1 && Ch(0) == 'e' && (V(2) || Ch(2) == 'h'))
                        {
                            Emit(Phoneme.G, i); // « exemple »
                            Emit(Phoneme.Z, i);
                        }
                        else if (s.Contains("xième"))
                            Emit(Phoneme.Z, i); // « deuxième »
                        else
                        {
                            Emit(Phoneme.K, i); // « taxi »
                            Emit(Phoneme.S, i);
                        }
                        i += 1;
                        break;
                    case 'w':
                        Emit(Phoneme.W, i);
                        i += 1;
                        break;
                    case 'ñ':
                        Emit(Phoneme.Gn, i);
                        i += 1;
                        break;
                    case 'ß':
                        Emit(Phoneme.S, i);
                        i += 1;
                        break;
                    case 'b': i += Doubled(i, Phoneme.B); break;
                    case 'd': i += Doubled(i, Phoneme.D); break;
                    case 'f': i += Doubled(i, Phoneme.F); break;
                    case 'k': i += Doubled(i, Phoneme.K); break;
                    case 'l': i += Doubled(i, Phoneme.L); break;
                    case 'm': i += Doubled(i, Phoneme.M); break;
                    case 'n': i += Doubled(i, Phoneme.N); break;
                    case 'r': i += Doubled(i, Phoneme.R); break;
                    case 'v': i += Doubled(i, Phoneme.V); break;
                    case 'z': i += Doubled(i, Phoneme.Z); break;
                    default:
                        // Lettre hors du français (autre écriture) : une ouverture neutre, pour que la bouche bouge
                        // quand la voix parle.
                        Emit(Phoneme.Schwa, i);
                        i += 1;
                        break;
                }
            }
        }

        // ── Nombres ─────────────────────────────────────────────────────────

        static readonly string[] Units =
        {
            "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
            "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
        };

        static readonly Dictionary<int, string> Tens = new Dictionary<int, string>
        {
            [2] = "vingt", [3] = "trente", [4] = "quarante", [5] = "cinquante", [6] = "soixante",
        };

        static string Below100(int n)
        {
            if (n < 17)
                return Units[n];
            if (n < 20)
                return "dix-" + Units[n - 10];
            int tens = n / 10;
            int unit = n % 10;
            if (tens == 7)
                return unit == 1 ? "soixante et onze" : "soixante-" + Below100(10 + unit);
            if (tens == 8)
                return unit == 0 ? "quatre-vingts" : "quatre-vingt-" + Units[unit];
            if (tens == 9)
                return "quatre-vingt-" + Below100(10 + unit);
            string name = Tens[tens];
            if (unit == 0)
                return name;
            return unit == 1 ? name + " et un" : name + "-" + Units[unit];
        }

        static string Below1000(int n)
        {
            int hundreds = n / 100;
            int rest = n % 100;
            string head = hundreds == 0 ? "" : hundreds == 1 ? "cent" : Units[hundreds] + " cent" + (rest == 0 ? "s" : "");
            var parts = new List<string>();
            if (head.Length > 0)
                parts.Add(head);
            if (rest != 0)
                parts.Add(Below100(rest));
            return string.Join(" ", parts);
        }

        /// <summary>
        /// Écrit un entier en toutes lettres, comme la synthèse le lit. Au-delà de neuf chiffres, ou avec un zéro
        /// de tête (« 06… »), chiffre par chiffre.
        /// </summary>
        public static string SpellNumber(string digits)
        {
            if (digits.Length > 9 || (digits.Length > 1 && digits[0] == '0'))
                return string.Join(" ", digits.Select(d => Units[d - '0']));
            int n = int.Parse(digits, CultureInfo.InvariantCulture);
            if (n == 0)
                return Units[0];
            int millions = n / 1000000;
            int thousands = n / 1000 % 1000;
            int rest = n % 1000;
            var parts = new List<string>();
            if (millions != 0)
                parts.Add(millions == 1 ? "un million" : Below1000(millions) + " millions");
            if (thousands != 0)
                parts.Add(thousands == 1 ? "mille" : Below1000(thousands) + " mille");
            if (rest != 0)
                parts.Add(Below1000(rest));
            return string.Join(" ", parts);
        }

        // ── Analyse ─────────────────────────────────────────────────────────

        enum UnitKind { Word, Number, Space, Pause, Symbol }

        sealed class Unit
        {
            public UnitKind Kind;
            public int From;
            /// <summary>Poids temporel en caractères (la longueur aux blancs repliés).</summary>
            public int Chars;
            public List<PhonemeToken> Phonemes;
        }

        /// <summary>Lettres d'un fragment, diacritiques combinants recomposés sur leur base (un « é » décomposé
        /// reste une lettre, à l'index de sa base).</summary>
        static void ComposeLetters(string text, int from, int to, out string orig, out string lower, out List<int> pos)
        {
            var o = new StringBuilder();
            var l = new StringBuilder();
            pos = new List<int>();
            for (int k = from; k < to; k++)
            {
                char c = text[k];
                if (IsMark(c))
                {
                    if (pos.Count == 0)
                        continue;
                    string composed = (o[o.Length - 1].ToString() + c).Normalize(NormalizationForm.FormC);
                    if (composed.Length == 1)
                    {
                        o[o.Length - 1] = composed[0];
                        l[l.Length - 1] = composed.ToLowerInvariant()[0];
                    }
                    continue;
                }
                o.Append(c);
                l.Append(c.ToString().ToLowerInvariant().Normalize(NormalizationForm.FormC)[0]);
                pos.Add(k);
            }
            orig = o.ToString();
            lower = l.ToString();
        }

        /// <summary>Un mot, apostrophes et traits d'union compris : chaque fragment est phonétisé à part
        /// (« qu'est-ce », « peut-être »). Renvoie le dernier fragment, contexte du mot suivant.</summary>
        static string PronounceWordUnit(string text, int from, int to, string prev, List<PhonemeToken> output)
        {
            int k = from;
            while (k < to)
            {
                int e = k;
                while (e < to && !IsJoiner(text[e]))
                    e++;
                ComposeLetters(text, k, e, out var orig, out var lower, out var pos);
                bool elided = e < to && IsApostrophe(text[e]);
                PronounceWord(lower, orig, pos, prev, elided, output);
                prev = lower;
                k = e + 1;
            }
            return prev;
        }

        static readonly Regex NumberWord = new Regex(@"[^\s-]+", RegexOptions.CultureInvariant);

        /// <summary>Phonèmes d'un nombre écrit en toutes lettres, ramenés sur ses chiffres : l'index est
        /// interpolé le long de « 2026 » pour rester monotone.</summary>
        static List<PhonemeToken> NumberPhonemes(string spelled, int from, int to)
        {
            var local = new List<PhonemeToken>();
            string prev = "";
            foreach (Match match in NumberWord.Matches(spelled))
            {
                int at = match.Index;
                ComposeLetters(spelled, at, at + match.Length, out var orig, out var lower, out var pos);
                PronounceWord(lower, orig, pos, prev, false, local);
                prev = lower;
            }
            int width = to - from;
            return local.Select(t => new PhonemeToken(t.Ph, from + (int)Math.Floor((double)t.At * width / spelled.Length))).ToList();
        }

        static List<Unit> Analyze(string text)
        {
            var units = new List<Unit>();
            text ??= "";
            int n = text.Length;
            string prevWord = "";
            int i = 0;
            while (i < n)
            {
                char c = text[i];
                int j = i + 1;
                if (IsSpace(c))
                {
                    while (j < n && IsSpace(text[j]))
                        j++;
                    units.Add(new Unit { Kind = UnitKind.Space, From = i, Chars = 1, Phonemes = new List<PhonemeToken>() });
                }
                else if (IsDigit(c))
                {
                    while (j < n && IsDigit(text[j]))
                        j++;
                    string spelled = SpellNumber(text.Substring(i, j - i));
                    units.Add(new Unit { Kind = UnitKind.Number, From = i, Chars = spelled.Length, Phonemes = NumberPhonemes(spelled, i, j) });
                    prevWord = "";
                }
                else if (IsLetter(c))
                {
                    while (j < n)
                    {
                        if (IsLetter(text[j]) || IsMark(text[j]))
                            j++;
                        else if (IsJoiner(text[j]) && j + 1 < n && IsLetter(text[j + 1]))
                            j++;
                        else
                            break;
                    }
                    var phonemes = new List<PhonemeToken>();
                    prevWord = PronounceWordUnit(text, i, j, prevWord, phonemes);
                    units.Add(new Unit { Kind = UnitKind.Word, From = i, Chars = j - i, Phonemes = phonemes });
                }
                else
                {
                    while (j < n && !IsSpace(text[j]) && !IsDigit(text[j]) && !IsLetter(text[j]))
                        j++;
                    bool pause = false;
                    for (int k = i; k < j; k++)
                        if (PausePunct.IndexOf(text[k]) >= 0)
                            pause = true;
                    if (pause)
                        prevWord = "";
                    units.Add(new Unit { Kind = pause ? UnitKind.Pause : UnitKind.Symbol, From = i, Chars = j - i, Phonemes = new List<PhonemeToken>() });
                }
                i = j;
            }
            return units;
        }

        /// <summary>Phonèmes du texte, dans l'ordre (tests et debug).</summary>
        public static List<PhonemeToken> Phonemes(string text) => Analyze(text).SelectMany(u => u.Phonemes).ToList();

        /// <summary>Les phonèmes du texte en symboles séparés par des espaces (« m i k a ») — tests et debug.</summary>
        public static string PhonemeString(string text) => string.Join(" ", Phonemes(text).Select(t => Symbol(t.Ph)));

        /// <summary>Longueur temporelle d'un texte en caractères : blancs repliés, nombres comptés en toutes
        /// lettres. <c>durée = msPerChar × SpokenLength</c>.</summary>
        public static int SpokenLength(string text) => Analyze(text).Sum(u => u.Chars);

        /// <summary>Variation déterministe dans [0, 1) — même texte, même bouche.</summary>
        static double Hash01(double x)
        {
            double v = Math.Sin(x * 12.9898 + 78.233) * 43758.5453;
            return v - Math.Floor(v);
        }

        sealed class Draft
        {
            public Viseme Viseme;
            public float Weight;
            public float Length;
            public int At;
            public bool Fixed;
            public bool Gap;
        }

        /// <summary>
        /// Frames de visèmes d'un segment prononcé. <paramref name="start"/> est l'index du segment dans la
        /// réplique complète (−1 : pas de position, les frames portent −1). Les blancs et la ponctuation ont une
        /// durée fixe ; le reste du budget se répartit sur les phonèmes au prorata de leur durée relative — un mot
        /// dure ce qu'il se prononce, et le total reste <c>msPerChar × SpokenLength(text)</c>.
        /// </summary>
        public static List<VisemeFrame> Frames(string text, float msPerChar, int start = -1)
        {
            float ms = !float.IsNaN(msPerChar) && !float.IsInfinity(msPerChar) && msPerChar > 0f ? msPerChar : 0f;
            var units = Analyze(text);
            float total = ms * units.Sum(u => u.Chars);

            var drafts = new List<Draft>();
            int lastVowel = -1;
            void Lengthen()
            {
                if (lastVowel >= 0)
                    drafts[lastVowel].Length *= FinalLengthening;
                lastVowel = -1;
            }

            foreach (var unit in units)
            {
                switch (unit.Kind)
                {
                    case UnitKind.Space:
                        drafts.Add(new Draft { Viseme = Viseme.Sil, Length = ms * SpaceGapShare, At = unit.From, Fixed = true, Gap = true });
                        break;
                    case UnitKind.Symbol:
                        drafts.Add(new Draft { Viseme = Viseme.Sil, Length = ms * unit.Chars, At = unit.From, Fixed = true, Gap = true });
                        break;
                    case UnitKind.Pause:
                        Lengthen();
                        drafts.Add(new Draft { Viseme = Viseme.Sil, Length = ms * unit.Chars, At = unit.From, Fixed = true });
                        break;
                    default:
                        foreach (var token in unit.Phonemes)
                        {
                            var p = Info(token.Ph);
                            if (p.Vowel)
                                lastVowel = drafts.Count;
                            float jitter = 1f - WeightJitter / 2f + WeightJitter * (float)Hash01(token.At + drafts.Count);
                            drafts.Add(new Draft
                            {
                                Viseme = p.Viseme,
                                Weight = Math.Min(1f, p.Weight * (p.Vowel ? jitter : 1f)),
                                Length = p.Length,
                                At = token.At,
                            });
                        }
                        break;
                }
            }
            Lengthen();

            float fixedSum = 0f, relative = 0f;
            foreach (var d in drafts)
            {
                if (d.Fixed)
                    fixedSum += d.Length;
                else
                    relative += d.Length;
            }
            float free = Math.Max(0f, total - fixedSum);

            var frames = new List<VisemeFrame>(drafts.Count);
            foreach (var d in drafts)
            {
                frames.Add(new VisemeFrame
                {
                    Viseme = d.Viseme,
                    Weight = d.Weight,
                    Duration = d.Fixed ? d.Length : relative > 0f ? free * d.Length / relative : 0f,
                    CharOffset = start >= 0 ? start + d.At : -1,
                    Gap = d.Gap,
                });
            }
            // Rien d'articulé (« … ») : le temps restant tient sur la dernière frame plutôt que de disparaître.
            if (relative == 0f && free > 0f && frames.Count > 0)
            {
                var last = frames[frames.Count - 1];
                last.Duration += free;
                frames[frames.Count - 1] = last;
            }
            return frames;
        }
    }
}
