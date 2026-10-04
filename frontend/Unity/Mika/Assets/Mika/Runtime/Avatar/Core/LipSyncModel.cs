using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Mika.Avatar
{
    /// <summary>
    /// La bouche qui articule le français que la voix prononce. Portage de
    /// <c>frontend/src/audio/LipSyncController.ts</c>, sans le modèle : ce cœur avance un curseur dans les frames
    /// de visèmes, calcule une cible coarticulée et la poursuit, et rend 15 niveaux (un par visème) ; c'est
    /// <see cref="VisemeRouting"/> qui les écrit sur les formes du modèle.
    /// </summary>
    /// <remarks>
    /// Il n'y a pas de synthèse vocale dans le client Unity : la bouche est pilotée depuis le texte, au débit
    /// estimé — exactement l'estimation du web entre deux recalages. <see cref="Seek"/> recale le curseur sur
    /// une position de lecture (index de caractère) quand une vraie voix en rapportera une.
    /// </remarks>
    public sealed class LipSyncModel
    {
        // ── Coarticulation ──────────────────────────────────────────────────
        // On ne passe pas d'une forme à l'autre au changement de frame : la bouche prépare la suivante avant de
        // quitter la courante, et les muscles ont des vitesses différentes selon le geste.

        /// <summary>Dernière fraction d'une frame qui glisse déjà vers la suivante…</summary>
        const float Anticipation = 0.3f;
        /// <summary>…bornée en temps : une pause de 600 ms ne prépare pas le mot suivant pendant 180 ms.</summary>
        const float AnticipationMaxMs = 70f;
        /// <summary>Ouverture conservée à travers un blanc entre deux mots.</summary>
        const float GapOpenness = 0.7f;
        /// <summary>Attaque (1/s) : τ ≈ 21 ms pour une fermeture, 33 ms pour une autre consonne, 42 ms pour une voyelle.</summary>
        const float AttackClosure = 48f, AttackConsonant = 30f, AttackVowel = 24f;
        /// <summary>Retour au repos : plus lent que toute attaque, la bouche se détend, elle ne claque pas.</summary>
        const float Release = 12f;
        /// <summary>Passage de relais d'une forme à une autre : la sortante s'efface à peu près au rythme où
        /// l'entrante arrive (relâcher au rythme du repos laissait les lèvres mi-closes sur la voyelle après un « p »).</summary>
        const float Crossfade = 26f;
        /// <summary>…et plus vite encore quand c'est une fermeture qui arrive, sinon l'occlusive ne se lit pas.</summary>
        const float Yield = 40f;
        /// <summary>Cible totale au-dessus de laquelle une forme sortante est un relais et non un retour au repos.</summary>
        const float TransitionMin = 0.15f;
        /// <summary>Poids de forme au-dessus duquel une fermeture « tient » la cible.</summary>
        const float ClosureDominance = 0.3f;

        const float ArticulationMin = 0.4f, ArticulationMax = 1.2f;
        /// <summary>Part de la réduction d'articulation subie par les fermetures : une voix lasse ouvre moins la
        /// bouche, mais ses « p » ferment toujours les lèvres.</summary>
        const float ClosureArticulationShare = 0.3f;

        public const int VisemeCount = 15;
        const int SilIndex = (int)Viseme.Sil;

        static readonly bool[] IsClosure = new bool[VisemeCount];
        static readonly float[] AttackRates = new float[VisemeCount];

        static LipSyncModel()
        {
            for (int c = 0; c < VisemeCount; c++)
            {
                var v = (Viseme)c;
                bool closure = v == Viseme.PP || v == Viseme.FF || v == Viseme.SS;
                bool vowel = v == Viseme.AA || v == Viseme.E || v == Viseme.IH || v == Viseme.OH || v == Viseme.OU;
                IsClosure[c] = closure;
                AttackRates[c] = closure ? AttackClosure : vowel ? AttackVowel : AttackConsonant;
            }
        }

        readonly float[] _level = new float[VisemeCount];
        readonly float[] _target = new float[VisemeCount];
        readonly float[] _shapeA = new float[VisemeCount];
        readonly float[] _shapeB = new float[VisemeCount];
        readonly List<string> _cues = new List<string>();
        List<VisemeFrame> _frames = new List<VisemeFrame>();
        int _frameIndex;
        float _frameTimer;
        float _articulation = 1f;

        /// <summary>
        /// Quand une vraie voix pilote la bouche : la fin des frames ne termine PAS la parole (la voix peut être
        /// plus lente que l'estimation) — la bouche se repose fermée jusqu'au prochain recalage ou à
        /// <see cref="Stop"/>.
        /// </summary>
        public bool HoldAtEnd { get; set; }

        public bool IsSpeaking { get; private set; }

        /// <summary>Niveaux lissés des 15 visèmes (ce que la bouche montre), dans l'ordre de <see cref="Viseme"/>.</summary>
        public IReadOnlyList<float> Levels => _level;

        /// <summary>Le plan en cours (lecture seule) — tests et debug.</summary>
        public IReadOnlyList<VisemeFrame> Frames => _frames;

        /// <summary>Caractère de la frame courante (−1 hors plan ou sur un silence).</summary>
        public int CurrentCharOffset => _frameIndex < _frames.Count ? _frames[_frameIndex].CharOffset : -1;

        /// <summary>Visème de la frame courante (<c>Sil</c> hors plan).</summary>
        public Viseme CurrentViseme => _frameIndex < _frames.Count ? _frames[_frameIndex].Viseme : Viseme.Sil;

        /// <summary>
        /// Amplitude des mouvements de bouche (0,4–1,2 ; 1 = normal). Une voix lasse ou triste articule moins ;
        /// les fermetures n'en subissent qu'une part, pour que les « p » restent des « p ».
        /// </summary>
        public void SetArticulation(float scale) =>
            _articulation = float.IsNaN(scale) || float.IsInfinity(scale) ? 1f : Math.Max(ArticulationMin, Math.Min(ArticulationMax, scale));

        public void Begin(IEnumerable<VisemeFrame> frames)
        {
            _frames = new List<VisemeFrame>(frames ?? Array.Empty<VisemeFrame>());
            _frameIndex = 0;
            _frameTimer = 0f;
            _cues.Clear();
            IsSpeaking = _frames.Count > 0;
            if (IsSpeaking)
                NoteCue(0);
        }

        public void Stop()
        {
            IsSpeaking = false;
            _frames.Clear();
            _frameIndex = 0;
            _frameTimer = 0f;
            _cues.Clear();
        }

        /// <summary>
        /// Recale le curseur sur le caractère que la voix est en train de prononcer — en avant comme en
        /// arrière, et une estimation finie trop tôt repart. Au-delà du dernier caractère voisé (ponctuation
        /// finale), se pose sur la dernière frame voisée. Renvoie false si le plan n'a aucune frame positionnée.
        /// </summary>
        public bool Seek(int charIndex)
        {
            if (_frames.Count == 0)
                return false;
            int target = -1;
            for (int i = 0; i < _frames.Count; i++)
            {
                int offset = _frames[i].CharOffset;
                if (offset < 0)
                    continue;
                if (offset >= charIndex)
                {
                    target = i;
                    break;
                }
            }
            if (target < 0)
            {
                for (int i = _frames.Count - 1; i >= 0; i--)
                {
                    if (_frames[i].CharOffset >= 0)
                    {
                        target = i;
                        break;
                    }
                }
                if (target < 0)
                    return false;
            }
            _frameIndex = target;
            _frameTimer = 0f;
            IsSpeaking = true;
            return true;
        }

        /// <summary>Les repères prosodiques atteints depuis le dernier appel (vidés à la lecture).</summary>
        public void DrainCues(List<string> into)
        {
            into.AddRange(_cues);
            _cues.Clear();
        }

        /// <summary>Avance la bouche de <paramref name="dt"/> secondes.</summary>
        public void Update(float dt)
        {
            if (!(dt > 0f) || float.IsInfinity(dt))
                dt = 0f;
            Array.Clear(_target, 0, VisemeCount);
            if (IsSpeaking && _frames.Count > 0)
            {
                _frameTimer += dt * 1000f;
                while (_frameIndex < _frames.Count && _frameTimer >= _frames[_frameIndex].Duration)
                {
                    _frameTimer -= _frames[_frameIndex].Duration;
                    _frameIndex++;
                    NoteCue(_frameIndex);
                }
                if (_frameIndex < _frames.Count)
                    CoarticulatedTarget(_target);
                else if (HoldAtEnd)
                {
                    // La voix réelle n'a pas fini : on reste en fin de plan, bouche au repos.
                    _frameIndex = _frames.Count;
                    _frameTimer = 0f;
                }
                else
                    IsSpeaking = false;
            }
            Follow(_target, dt);
        }

        void NoteCue(int index)
        {
            if (index < _frames.Count && _frames[index].Cue != null)
                _cues.Add(_frames[index].Cue);
        }

        /// <summary>
        /// Forme visée maintenant : celle de la frame courante, fondue dans sa dernière part vers celle de la
        /// suivante. Le fondu atteint la suivante pile à la frontière : la cible est continue.
        /// </summary>
        void CoarticulatedTarget(float[] output)
        {
            var frame = _frames[_frameIndex];
            float progress = frame.Duration > 0f ? Math.Min(1f, _frameTimer / frame.Duration) : 1f;
            ShapeAt(_frameIndex, progress, _shapeA);
            float blend = 0f;
            if (_frameIndex + 1 < _frames.Count)
            {
                float window = Math.Min(Anticipation * frame.Duration, AnticipationMaxMs);
                float remaining = frame.Duration - _frameTimer;
                if (window > 0f && remaining < window)
                    blend = Smooth(1f - remaining / window);
            }
            if (blend > 0f)
            {
                ShapeAt(_frameIndex + 1, 0f, _shapeB);
                for (int c = 0; c < VisemeCount; c++)
                    output[c] = _shapeA[c] * (1f - blend) + _shapeB[c] * blend;
            }
            else
                Array.Copy(_shapeA, output, VisemeCount);
        }

        /// <summary>Un blanc entre deux mots glisse de la forme précédente à la suivante sans refermer la
        /// bouche ; une pause la referme.</summary>
        void ShapeAt(int index, float progress, float[] output)
        {
            Array.Clear(output, 0, VisemeCount);
            if (index < 0 || index >= _frames.Count)
                return;
            var frame = _frames[index];
            if (!frame.Gap)
            {
                AddShape(index, output, 1f);
                return;
            }
            int before = index - 1;
            while (before >= 0 && _frames[before].Gap)
                before--;
            int after = index + 1;
            while (after < _frames.Count && _frames[after].Gap)
                after++;
            float t = Smooth(progress);
            AddShape(before, output, (1f - t) * GapOpenness);
            AddShape(after, output, t * GapOpenness);
        }

        void AddShape(int index, float[] output, float scale)
        {
            if (index < 0 || index >= _frames.Count)
                return;
            var f = _frames[index];
            if (f.Gap || f.Viseme == Viseme.Sil)
                return;
            output[(int)f.Viseme] += f.Weight * scale;
        }

        /// <summary>
        /// Poursuite asymétrique : attaque rapide des fermetures, plus lente des voyelles ; une forme qui sort
        /// s'efface au rythme de celle qui entre (vite si c'est une fermeture), lentement seulement quand la
        /// bouche retourne au repos.
        /// </summary>
        void Follow(float[] target, float dt)
        {
            float art = _articulation;
            float closureArt = 1f - (1f - art) * ClosureArticulationShare;
            int dominant = SilIndex;
            float wanted = 0f;
            for (int c = 0; c < VisemeCount; c++)
            {
                wanted += target[c];
                if (target[c] > target[dominant])
                    dominant = c;
            }
            bool closing = IsClosure[dominant] && target[dominant] > ClosureDominance;
            bool handover = wanted > TransitionMin;
            for (int c = 0; c < VisemeCount; c++)
            {
                if (c == SilIndex)
                    continue;
                float goal = target[c] * (IsClosure[c] ? closureArt : art);
                float current = _level[c];
                float rate;
                if (goal > current)
                    rate = AttackRates[c];
                else if (closing && c != dominant)
                    rate = Yield;
                else
                    rate = handover ? Crossfade : Release;
                _level[c] = current + (goal - current) * (1f - MathF.Exp(-rate * dt));
            }
        }

        static float Smooth(float x)
        {
            float t = Emotions.Clamp01(x);
            return t * t * (3f - 2f * t);
        }
    }

    /// <summary>
    /// Visème par visème, où écrire : le morph VRChat <c>vrc.v_*</c> (exposé en <c>raw:</c>) quand le modèle le
    /// porte, sinon les cinq presets VRM (<c>aa ih ou ee oh</c>). Plus le plafond d'ouverture : d'autres couches
    /// écrivent sur la même bouche (sourire, micro-mouvements) et les morphs s'additionnent sur les sommets — un
    /// « a » plein sur une bouche déjà ouverte par la surprise déformerait le visage.
    /// </summary>
    public sealed class VisemeRouting
    {
        /// <summary>
        /// Repli sur les presets. Une fermeture (<c>PP</c>) n'a pas de preset : c'est la bouche au repos, que
        /// l'attaque rapide rend lisible entre deux voyelles. Les voyelles plafonnent sous 1 : un preset est une
        /// forme pleine, et les modèles génériques l'ont souvent généreuse.
        /// </summary>
        public static readonly IReadOnlyDictionary<Viseme, IReadOnlyDictionary<string, float>> PresetFallback =
            new Dictionary<Viseme, IReadOnlyDictionary<string, float>>
            {
                [Viseme.Sil] = P(),
                [Viseme.PP] = P(),
                [Viseme.FF] = P(("ih", 0.25f)),
                [Viseme.TH] = P(("ee", 0.2f), ("aa", 0.1f)),
                [Viseme.DD] = P(("ih", 0.3f), ("aa", 0.12f)),
                [Viseme.KK] = P(("aa", 0.3f), ("ih", 0.15f)),
                [Viseme.CH] = P(("ou", 0.45f), ("ih", 0.15f)),
                [Viseme.SS] = P(("ih", 0.35f), ("ee", 0.25f)),
                [Viseme.NN] = P(("ih", 0.25f), ("aa", 0.1f)),
                [Viseme.RR] = P(("ou", 0.25f), ("aa", 0.15f)),
                [Viseme.AA] = P(("aa", 0.8f)),
                [Viseme.E] = P(("ee", 0.6f), ("aa", 0.15f)),
                [Viseme.IH] = P(("ih", 0.7f)),
                [Viseme.OH] = P(("oh", 0.75f)),
                [Viseme.OU] = P(("ou", 0.75f)),
            };

        public static readonly IReadOnlyList<string> MouthPresets = new[] { "aa", "ih", "ou", "ee", "oh" };

        /// <summary>Somme maximale des visèmes entre eux (deux formes en fondu = une bouche).</summary>
        public const float MaxVisemeSum = 1f;
        /// <summary>Somme maximale visèmes + charge buccale des autres expressions.</summary>
        public const float MaxMouthTotal = 1.3f;
        /// <summary>Ce que la parole garde au minimum, même sur un visage hilare.</summary>
        public const float MinVisemeAllowance = 0.45f;

        /// <summary>Les morphs VRChat que le visage cherche sur le modèle (tous les visèmes sauf <c>sil</c>).</summary>
        public static IEnumerable<string> VrcMorphs()
        {
            foreach (var v in FrenchVisemes.All)
                if (v != Viseme.Sil)
                    yield return FrenchVisemes.VrcMorph(v);
        }

        readonly struct Route
        {
            public readonly int Viseme;
            public readonly int Out;
            public readonly float Factor;
            public Route(int viseme, int output, float factor) { Viseme = viseme; Out = output; Factor = factor; }
        }

        readonly List<Route> _routes = new List<Route>();
        readonly List<string> _outputs = new List<string>();
        float[] _values;

        /// <summary>Combien de visèmes passent par les morphs VRChat (14 = tous).</summary>
        public int RawVisemes { get; }

        /// <summary>Les noms d'expression que le routage écrit (pour exclure la bouche elle-même de la charge).</summary>
        public IReadOnlyList<string> Outputs => _outputs;

        /// <summary><c>visemes</c> : les 14 morphs VRChat ; <c>presets</c> : les 5 voyelles VRM ; <c>mixed</c> : un jeu
        /// VRChat incomplet, complété par les presets.</summary>
        public string Mode => RawVisemes == VisemeCountDriven ? "visemes" : RawVisemes == 0 ? "presets" : "mixed";

        const int VisemeCountDriven = LipSyncModel.VisemeCount - 1;

        /// <param name="hasRawMorph">Le modèle porte ce morph <c>vrc.v_*</c> (et l'expression <c>raw:</c> a été créée).</param>
        /// <param name="hasPreset">Le modèle porte ce preset de bouche.</param>
        public VisemeRouting(Func<string, bool> hasRawMorph, Func<string, bool> hasPreset)
        {
            hasRawMorph ??= _ => false;
            hasPreset ??= _ => false;
            int raw = 0;
            foreach (var v in FrenchVisemes.All)
            {
                if (v == Viseme.Sil)
                    continue;
                string morph = FrenchVisemes.VrcMorph(v);
                if (hasRawMorph(morph))
                {
                    _routes.Add(new Route((int)v, IndexOf(FaceNames.Raw(morph)), 1f));
                    raw++;
                    continue;
                }
                foreach (var kv in PresetFallback[v])
                    if (hasPreset(kv.Key))
                        _routes.Add(new Route((int)v, IndexOf(kv.Key), kv.Value));
            }
            RawVisemes = raw;
            _values = new float[_outputs.Count];
        }

        int IndexOf(string name)
        {
            int i = _outputs.IndexOf(name);
            if (i < 0)
            {
                i = _outputs.Count;
                _outputs.Add(name);
            }
            return i;
        }

        /// <summary>
        /// Somme de visèmes permise : <see cref="MaxMouthTotal"/> moins ce que les autres expressions font déjà
        /// à la bouche, jamais sous <see cref="MinVisemeAllowance"/> ni au-dessus de <see cref="MaxVisemeSum"/>.
        /// </summary>
        public static float Allowance(float mouthLoad) =>
            Math.Max(MinVisemeAllowance, Math.Min(MaxVisemeSum, MaxMouthTotal - mouthLoad));

        /// <summary>
        /// Écrit (en les AJOUTANT) les niveaux sur les sorties, mis à l'échelle sous le plafond d'ouverture.
        /// </summary>
        public void Write(IReadOnlyList<float> levels, float mouthLoad, IDictionary<string, float> output)
        {
            float sum = 0f;
            for (int c = 0; c < levels.Count; c++)
                if (c != (int)Viseme.Sil)
                    sum += levels[c];
            float allowance = Allowance(mouthLoad);
            float scale = sum > allowance ? allowance / sum : 1f;
            Array.Clear(_values, 0, _values.Length);
            foreach (var r in _routes)
                _values[r.Out] += levels[r.Viseme] * r.Factor * scale;
            for (int o = 0; o < _outputs.Count; o++)
            {
                float v = Math.Min(1f, _values[o]);
                if (v <= 0.0005f)
                    continue;
                output.TryGetValue(_outputs[o], out var w);
                output[_outputs[o]] = w + v;
            }
        }

        static IReadOnlyDictionary<string, float> P(params (string name, float weight)[] parts)
        {
            var d = new Dictionary<string, float>();
            foreach (var (name, weight) in parts)
                d[name] = weight;
            return d;
        }
    }

    /// <summary>
    /// Ce que les autres expressions font déjà à la bouche : un « ou » probabiliste de poids × implication,
    /// pour que deux demi-sourires ne comptent pas double. L'implication d'une expression se lit, une fois,
    /// sur les noms des morphs qu'elle lie (<c>LipSyncController.ts::scanMouthLoads</c>).
    /// </summary>
    public static class MouthLoad
    {
        /// <summary>Morphs de bouche reconnus par leur nom (VRChat, ARKit, presets japonais).</summary>
        static readonly Regex MouthMorph = new Regex(@"mouth|jaw|lip|tongue|teeth|tooth|^vrc\.v_|^mth|^[あいうえおん]$",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        /// <summary>Ceux qui ouvrent la bouche comptent plein ; un sourire, une moue, à 40 %.</summary>
        static readonly Regex OpeningMorph = new Regex(@"open|jawopen|lowerdown|^あ$|^お$",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        public const float ShapeMorphFactor = 0.4f;

        /// <summary>Implication buccale d'une expression d'après ses liaisons (nom du morph, poids 0…1).</summary>
        public static float Involvement(IEnumerable<(string morph, float weight)> binds)
        {
            float involvement = 0f;
            foreach (var (morph, weight) in binds)
            {
                if (string.IsNullOrEmpty(morph) || !MouthMorph.IsMatch(morph))
                    continue;
                float factor = OpeningMorph.IsMatch(morph) ? 1f : ShapeMorphFactor;
                involvement = Math.Max(involvement, weight * factor);
            }
            return involvement;
        }

        /// <summary>Charge 0…1 à partir de couples (poids écrit, implication).</summary>
        public static float Combine(IEnumerable<(float weight, float involvement)> expressions)
        {
            float untouched = 1f;
            foreach (var (weight, involvement) in expressions)
                if (weight > 0.001f)
                    untouched *= 1f - Math.Min(1f, weight * involvement);
            return 1f - untouched;
        }
    }
}
