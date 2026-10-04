# Les gestes du bureau qui déplacent quelque chose : la chaise (tirée ou repoussée par les mains sur le bord du bureau,
# pivotée par les pieds qui poussent le sol), la tasse (prise par l'anse), le stylo (pris sur le carnet, tenu pour écrire
# ou pour le regarder, reposé à sa place). Aucun objet ne bouge sans une main ou un pied qui le déplace : chaque geste
# porte, image par image, ce qu'il fait bouger — la course de la chaise (courbes « ChairYaw » et « ChairRoll », le pivot
# et le roulement, 0 → 1), les mains posées
# sur le bureau (« HandsOnDesk ») et l'objet dans la main (« Hold » : 0 posé, 0,5 tenu tel qu'il a été pris, 1 tenu en
# main pour écrire). Unity reçoit ces courbes en paramètres de l'Animator et y synchronise la chaise et les objets.
#
# Chaque geste rend (image, objets, courbes) : `objets` donne, par identifiant d'objet de la pièce (« mug », « pen »), son
# déplacement rigide depuis sa place de repos (matrice monde du clip ; l'identité quand il est posé) — la vérification y
# pose le vrai modèle.
#
# Tout est construit sur la vraie géométrie du bureau (atelier_decor : relevé Unity, modèles de la pièce) : la chaise
# passe d'une position nommée à une autre (« home » → « type », « type » → « write »…), et les objets sont pris là
# où ils sont posés dans la pièce (build_desk.py), rendus exactement là.
import math

from mathutils import Matrix, Quaternion, Vector

import atelier_decor as dc
import atelier_lib as al

FPS = 30
Z = Vector((0.0, 0.0, 1.0))


def ad():
    import atelier_desk
    return atelier_desk


def ease(t, a, b):
    if t <= a:
        return 0.0
    if t >= b:
        return 1.0
    x = (t - a) / (b - a)
    return x * x * (3 - 2 * x)


# --- la géométrie --------------------------------------------------------------------------------------------------
class Geo:
    """Le bureau réel vu d'elle pour chaque position de la chaise (repère du clip), mis en cache."""

    def __init__(self, layout):
        self.layout = layout
        self._features = {}
        self.grips = layout.grips()

    def pose(self, name):
        return self.layout.chair_pose(name)

    def features(self, name):
        if name not in self._features:
            self._features[name] = dc.features(self.layout, self.pose(name))
        return self._features[name]

    def grip(self, side, chair):
        """La prise d'une main sur le bord du bureau (repère du clip), la chaise en `chair` ((pivot, roulement))."""
        g = self.grips[0 if side == "left" else 1]
        return dc.to_clip((g.x, 0.76, g.y), chair)

    def edge_inward(self, chair):
        """La direction vers le fond du bureau, perpendiculaire à son bord (repère du clip, à plat)."""
        e0, e1, n = self.layout.desk_edge()
        a = dc.to_clip((e0.x, 0.76, e0.y), chair)
        b = dc.to_clip((e0.x + n.x, 0.76, e0.y + n.y), chair)
        d = b - a
        d.z = 0.0
        return d.normalized()


def mirror_v(v):
    return Vector((-v.x, v.y, v.z))


def lerp_chair(a, b, s):
    return a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s


# --- la main : orientation et prise --------------------------------------------------------------------------------
def hand_world(desk, side, delta):
    """L'orientation monde de l'os de la main pour un changement d'orientation `delta` (convention de l'atelier)."""
    return delta @ desk.rig.rest[f"{side}Hand"]


def hand_delta(desk, side, world):
    return world @ desk.rig.rest[f"{side}Hand"].inverted()


def grip_offset(desk, side, delta, curl_fn, point):
    """
    Du poignet (tête de l'os de la main) au point de prise, au monde, la main orientée `delta` et les doigts pliés par
    `curl_fn(frame)` ; `point(pose)` donne le point de prise sur la pose calculée.
    """
    a = ad()
    f = a.copy(desk.seated)
    f["d"][f"{side}Hand"] = delta.copy()
    for k in list(f["d"]):
        if k.startswith(side) and any(x in k for x in a.FINGERS + ("Thumb",)):
            f["d"][k] = delta.copy()
    curl_fn(f)
    pose = desk.rig.fk(f)
    wrist = pose[desk.rig.hmap[f"{side}Hand"]].translation
    return point(pose) - wrist


def head(desk, pose, h):
    return pose[desk.rig.hmap[h]].translation


def handle_grip_point(desk, side):
    """Le point de prise d'une anse : entre les phalanges intermédiaires de l'index et du majeur (ils passent dans l'anse)."""
    return lambda pose: (head(desk, pose, f"{side}IndexIntermediate") + head(desk, pose, f"{side}MiddleIntermediate")) / 2


def pinch_point(desk, side):
    """Le point de pince : entre le bout du pouce et le bout de l'index."""
    a = ad()

    def at(pose):
        tips = []
        for name in ("Index", "Thumb"):
            h = f"{side}{name}Distal"
            b = desk.rig.arm.data.bones[desk.rig.hmap[h]]
            length = ((desk.rig.world @ b.tail_local) - (desk.rig.world @ b.head_local)).length
            m = pose[desk.rig.hmap[h]]
            tips.append(m.translation + m.to_3x3() @ Vector((0.0, length * 0.8, 0.0)))
        return (tips[0] + tips[1]) / 2
    return at


def handle_curl(desk, side, k=1.0):
    """Les doigts dans l'anse : l'index et le majeur la traversent et l'enserrent, annulaire et auriculaire repliés
    dessous, le pouce posé sur son dessus."""
    a = ad()
    return lambda f: a.curl(desk, f, side, {"Index": (35 * k, 70 * k, 35 * k), "Middle": (35 * k, 70 * k, 35 * k),
                                            "Ring": (55 * k, 75 * k, 35 * k), "Little": (60 * k, 75 * k, 35 * k)},
                            thumb=(25 * k, 10 * k, 5 * k), spread=0.0)


def pinch_curl(desk, side, k=1.0):
    """La pince du pouce et de l'index ; les autres doigts un peu repliés."""
    a = ad()
    return lambda f: a.curl(desk, f, side, {"Index": (30 * k, 35 * k, 15 * k), "Middle": (35 * k, 45 * k, 20 * k),
                                            "Ring": (45 * k, 50 * k, 20 * k), "Little": (50 * k, 50 * k, 20 * k)},
                            thumb=(35 * k, 20 * k, 10 * k), spread=0.0)


def arc(a, b, k, lift=0.07):
    """Un chemin de main de `a` à `b` (k : 0 → 1) qui monte d'abord près du corps (elle regarde −Y : le point le plus
    proche d'elle a le plus grand y), passe au-dessus et redescend — en ligne droite, une main venue de ses cuisses
    traversait le bord du bureau."""
    near = a if a.y >= b.y else b
    # Un peu en arrière du point près d'elle : la main redescend derrière le bord du bureau (en position d'écriture, il
    # passe juste au-dessus de sa cuisse droite), pas à travers.
    c = Vector(((a.x + b.x) / 2, near.y + 0.06, max(a.z, b.z) + lift))
    return a.lerp(c, k).lerp(c.lerp(b, k), k)


def rigid(rest_point, now_point, q):
    """Le déplacement rigide qui amène `rest_point` en `now_point` en tournant de q autour de lui."""
    return Matrix.Translation(now_point) @ q.to_matrix().to_4x4() @ Matrix.Translation(-rest_point)


# --- tirer et repousser la chaise : les mains sur le bord du bureau --------------------------------------------------
def desk_hand(desk, f, side, wrist_target, fingers, k_desk, start):
    """La main de ce côté : entre sa pose de départ (`start` : (poignet, delta)) et posée à plat sur le bureau, doigts vers
    `fingers` (vers le fond du bureau), le poids k_desk."""
    a = ad()
    sx = 1.0 if side == "left" else -1.0
    on = a.hand_rotation(desk, side, fingers + Vector((0.0, 0.0, -0.08)), Vector((-sx * 0.1, 0.0, -1.0)))
    w0, q0 = start
    # Le chemin de la main : elle monte d'abord près du corps, avance au-dessus du plateau et s'y pose (en ligne droite
    # depuis ses cuisses, elle traversait le bord du bureau).
    wrist = arc(w0, wrist_target, k_desk)
    q = q0.slerp(on, k_desk)
    a.arm_ik(desk, f, side, wrist, Vector((sx * 0.20, -0.04, 0.70)), None, None, hand_rot=q)
    a.relaxed(desk, f, side, 0.7 + 0.3 * (1.0 - k_desk))


def arm_state(desk, f, side):
    """(poignet, delta de la main) d'une image."""
    return desk.rig.joints(f, (f"{side}Hand",))[f"{side}Hand"].copy(), f["d"][f"{side}Hand"].copy()


SCOOT = 0.13          # ce que ses pieds font rouler la chaise en un pas (m) : au-delà, ses jambes n'y suffisent pas
SCOOT_LIFT = 0.03


def foot_home(desk, side):
    return desk.rig.joints(desk.seated, (f"{side}Foot",))[f"{side}Foot"]


def place_foot(desk, f, side, target, turn=None):
    """Le pied de ce côté amené en `target` (la jambe suit) ; `turn` (quaternion monde) tourne le pied et ses orteils."""
    if turn is not None:
        f["d"][f"{side}Foot"] = turn @ f["d"][f"{side}Foot"]
        if f"{side}Toes" in f["d"]:
            f["d"][f"{side}Toes"] = turn @ f["d"][f"{side}Toes"]
    al.two_bone(f, desk.rig, side, target)


def scoot(desk, f, t, t0, t1, forward):
    """
    Avancer (forward) ou reculer la chaise avec les pieds, de SCOOT, entre t0 et t1 : pour avancer, les pieds font un pas
    en avant puis restent au sol pendant que la chaise roule vers eux (les genoux se plient) ; pour reculer, ils poussent
    le sol (les genoux se déplient) puis reviennent sous elle d'un pas. Rend la part du roulement faite (0 → 1).
    """
    span = t1 - t0
    step_a, roll_a, roll_b, step_b = t0, t0 + 0.32 * span, t0 + 0.82 * span, t1
    rolled = ease(t, roll_a, roll_b)
    ahead = Vector((0.0, -1.0, 0.0))
    for side, delay in (("right", 0.0), ("left", 0.1 * span)):
        home = foot_home(desk, side)
        if forward:
            # Un pas en avant (avant de rouler), puis le pied reste au sol : il recule vers elle de la part roulée.
            step = ease(t, step_a + delay, step_a + delay + 0.22 * span)
            off = SCOOT * step - SCOOT * rolled
            lift = math.sin(math.pi * step) if 0.0 < step < 1.0 else 0.0
        else:
            # Il pousse : il avance par rapport à elle de la part roulée, puis un pas le ramène.
            step = ease(t, roll_b + delay * 0.5, roll_b + delay * 0.5 + 0.18 * span)
            off = SCOOT * rolled * (1.0 - step)
            lift = math.sin(math.pi * step) if 0.0 < step < 1.0 else 0.0
        place_foot(desk, f, side, home + ahead * off + Z * (SCOOT_LIFT * lift))
    return rolled


def hands_drive(desk, f, t, t_on, t_go, t_stop, t_off, chair, frm, to, period):
    """Les mains sur le bord du bureau entre t_on et t_off (posées, elles y restent pendant que la chaise roule), venues de
    la pose `frm` et rendues à la pose `to`."""
    a = ad()
    g = desk.geo
    on = ease(t, t_on - 0.45, t_on) * (1.0 - ease(t, t_stop + 0.05, t_off))
    poses = {}
    for name in (frm, to):
        fp = a.copy(f)
        if name == "desk":
            a.rest_arms(desk, fp, t, period)
        else:
            a.lap_hands(desk, fp, t, period)
        poses[name] = {side: arm_state(desk, fp, side) for side in ("left", "right")}
    inward = g.edge_inward(chair)
    for side in ("left", "right"):
        grip = g.grip(side, chair)
        wrist = grip - inward * 0.06 + Z * 0.035
        start_pose = poses[frm][side] if t < t_stop else poses[to][side]
        desk_hand(desk, f, side, wrist, inward, on, start_pose)
    return on


def chair_pull_in(desk, t, period):
    """
    Se rapprocher du bureau (de sa place d'origine à la position de frappe) : un pas des pieds fait d'abord rouler la
    chaise de SCOOT (le bord du bureau est trop loin pour ses bras), puis elle pose les mains à plat près du bord et
    tire, la chaise roulant et pivotant jusqu'à lui présenter le clavier ; ses mains restent sur le plateau.
    """
    a = ad()
    g = desk.geo
    c0, c1 = g.pose("home"), g.pose("type")
    share = SCOOT / max(1e-6, c1[1] - c0[1])
    t_feet_end = 1.15
    t_on, t_go, t_stop, t_off = 1.6, 1.65, period - 0.55, period - 0.1
    f = a.copy(desk.seated)
    rolled = scoot(desk, f, t, 0.0, t_feet_end, True)
    hand = ease(t, t_go, t_stop)
    roll_k = share * rolled + (1.0 - share) * hand
    yaw_k = hand
    chair = (c0[0] + (c1[0] - c0[0]) * yaw_k, c0[1] + (c1[1] - c0[1]) * roll_k)
    reach = max(-(g.grip("left", chair).y), -(g.grip("right", chair).y))
    on_now = ease(t, t_on - 0.45, t_on) * (1.0 - ease(t, t_stop + 0.05, t_off))
    lean_on = max(4.0, min(24.0, (reach - 0.22) * 80.0 + 6.0))
    a.lean(f, 4.0 + (lean_on - 4.0) * on_now - 3.0 * math.sin(math.pi * rolled), turn_deg=0.0)
    on = hands_drive(desk, f, t, t_on, t_go, t_stop, t_off, chair, "lap", "desk", period)
    # Pendant que les mains tirent, les pieds se soulèvent un peu (la chaise roule sous elle).
    up = ease(t, t_go - 0.15, t_go + 0.05) * (1.0 - ease(t, t_stop - 0.05, t_stop + 0.2))
    if up > 0.0:
        for side in ("left", "right"):
            place_foot(desk, f, side, foot_home(desk, side) + Vector((0.0, 0.01 * up, 0.025 * up)))
    a.look(desk, f, a.MONITOR["center"] + Vector((0.0, 0.0, -0.18)))
    return f, {}, {"ChairRoll": roll_k, "ChairYaw": yaw_k, "HandsOnDesk": on}


def chair_push_out(desk, t, period):
    """
    S'écarter du bureau (de la position de frappe à sa place d'origine) : les mains à plat près du bord, elle repousse la
    chaise, qui roule et pivote jusqu'à SCOOT de sa place ; puis ses pieds poussent le sol pour finir.
    """
    a = ad()
    g = desk.geo
    c0, c1 = g.pose("type"), g.pose("home")
    share = SCOOT / max(1e-6, c0[1] - c1[1])
    t_on, t_go, t_stop, t_off = 0.45, 0.5, 1.55, 1.95
    t_feet = 1.75
    f = a.copy(desk.seated)
    hand = ease(t, t_go, t_stop)
    rolled = scoot(desk, f, t, t_feet, period, False)
    roll_k = (1.0 - share) * hand + share * rolled
    yaw_k = hand
    chair = (c0[0] + (c1[0] - c0[0]) * yaw_k, c0[1] + (c1[1] - c0[1]) * roll_k)
    reach = max(-(g.grip("left", chair).y), -(g.grip("right", chair).y))
    on_now = ease(t, t_on - 0.45, t_on) * (1.0 - ease(t, t_stop + 0.05, t_off))
    lean_on = max(4.0, min(24.0, (reach - 0.22) * 80.0 + 6.0))
    base = 9.0 * (1.0 - ease(t, t_stop, t_off)) + 4.0 * ease(t, t_stop, t_off)
    a.lean(f, base + (lean_on - base) * on_now + 3.0 * math.sin(math.pi * rolled), turn_deg=0.0)
    on = hands_drive(desk, f, t, t_on, t_go, t_stop, t_off, chair, "desk", "lap", period)
    up = ease(t, t_go - 0.15, t_go + 0.05) * (1.0 - ease(t, t_stop - 0.05, t_stop + 0.2))
    if up > 0.0 and t < t_feet:
        for side in ("left", "right"):
            place_foot(desk, f, side, foot_home(desk, side) + Vector((0.0, 0.01 * up, 0.025 * up)))
    a.look(desk, f, a.MONITOR["center"] + Vector((0.0, 0.0, -0.18)))
    return f, {}, {"ChairRoll": roll_k, "ChairYaw": yaw_k, "HandsOnDesk": on}


# --- pivoter la chaise : les pieds poussent le sol ------------------------------------------------------------------
TURN_STANCE = 0.09     # les pieds avancés d'autant pour pivoter : au-delà des roulettes, rien sous eux ne tourne avec elle


def chair_turn(desk, t, period, degrees, pushes):
    """
    Pivoter la chaise vers sa gauche de `degrees`, en `pushes` poussées. Les pieds s'avancent d'abord un peu (au-delà des
    roulettes, que le piètement emporte en tournant) ; pendant une poussée ils restent au sol pendant que le bassin tourne
    (ses genoux restent en arrière du mouvement), puis chacun fait un pas pour revenir devant elle ; à la fin, ils
    reviennent sous elle. Le buste et la tête mènent. Vers la droite : le miroir.
    """
    a = ad()
    f = a.copy(desk.seated)
    t_in, t_out = 0.35, period - 0.35
    span = (t_out - t_in) / pushes
    push_len = span * 0.55
    turned = sum(ease(t, t_in + i * span, t_in + i * span + push_len) for i in range(pushes)) / pushes
    lead = math.sin(math.pi * min(1.0, turned * 1.1))
    a.lean(f, 6.0, turn_deg=10.0 * lead)
    a.lap_hands(desk, f, t, period)
    look_dir = math.radians(degrees * min(1.0, turned + 0.25 * lead))
    a.look(desk, f, Vector((math.sin(look_dir), -math.cos(look_dir), 0.0)) * 2.0 + Vector((0.0, 0.0, 1.0)))
    for side, delay in (("right", 0.0), ("left", 0.1)):
        home = foot_home(desk, side)
        out_dir = Vector((home.x, home.y, 0.0)).normalized()
        # S'avancer, revenir : un pas chacun.
        go = ease(t, 0.0 + delay, 0.25 + delay)
        back = ease(t, t_out + delay * 0.5, t_out + 0.25 + delay * 0.5)
        stance = home + out_dir * (TURN_STANCE * go * (1.0 - back))
        lift = 0.0
        for k in (go, back):
            if 0.0 < k < 1.0:
                lift = max(lift, math.sin(math.pi * k))
        ang = 0.0
        for i in range(pushes):
            t0 = t_in + i * span
            during = ease(t, t0, t0 + push_len)
            step = ease(t, t0 + push_len + delay, t0 + push_len + delay + 0.24)
            ang += (degrees / pushes) * during * (1.0 - step)
            if 0.0 < step < 1.0:
                lift = max(lift, math.sin(math.pi * step))
        # Le sol tourne de −angle par rapport à elle (elle tourne vers sa gauche : +Z dans le clip).
        q = Quaternion(Z, math.radians(-ang))
        place_foot(desk, f, side, q @ stance + Z * (0.035 * lift), turn=q)
    return f, {}, {"ChairYaw": turned}


def chair_turn_left_45(desk, t, period):
    return chair_turn(desk, t, period, 45.0, 2)


def chair_turn_left_90(desk, t, period):
    return chair_turn(desk, t, period, 90.0, 4)


# --- boire : la tasse prise par l'anse -------------------------------------------------------------------------------
def drink_geometry(desk):
    """La tasse en position de frappe, en miroir (le geste se construit de la main droite, se joue de la gauche)."""
    m = desk.geo.features("type")["mug"]
    return mirror_v(m["base"]), mirror_v(m["handle"]).normalized(), mirror_v(m["hole"])


def desk_drink(desk, t, period):
    """
    Boire : la main droite (jouée en miroir : la gauche) va prendre la tasse par l'anse — les doigts dedans, le pouce
    dessus —, la porte à ses lèvres, une gorgée, la repose exactement où elle était et revient sur le bureau.
    """
    a = ad()
    rig = desk.rig
    base, h, hole = drink_geometry(desk)
    # La prise : paume vers la tasse, pouce en haut, doigts dans l'axe du trou de l'anse.
    palm = -h
    fingers = palm.cross(Z).normalized()
    grip_q = a.hand_rotation(desk, "right", fingers + Vector((0.0, 0.0, -0.05)), palm)
    off = grip_offset(desk, "right", grip_q, handle_curl(desk, "right"), handle_grip_point(desk, "right"))
    grasp_wrist = hole - off
    timing = (0.4, 1.15, 1.9, 3.3, 4.0, 4.6)        # départ, prise, aux lèvres, quitte les lèvres, reposée, retour
    f = a.copy(desk.seated)
    breathe = math.sin(2 * math.pi * 2 * t / period)
    reach = ease(t, timing[0], timing[1]) * (1.0 - ease(t, timing[4], timing[5]))
    lift = ease(t, timing[1] + 0.15, timing[2]) * (1.0 - ease(t, timing[3], timing[4] - 0.05))
    # Penchée vers la tasse pour la prendre (elle est à la limite de ses bras), droite pour boire.
    a.lean(f, 9.0 + 0.6 * breathe + 7.0 * reach * (1.0 - lift), turn_deg=-10.0 * reach * (1.0 - lift), side_deg=-6.0 * reach * (1.0 - lift))
    a.rest_arms(desk, f, t, period, which=("left",))
    # La tasse aux lèvres : penchée de 35° vers elle, l'anse sur sa droite, le bord contre la lèvre inférieure.
    j = rig.joints(f, ("leftEye", "rightEye"))
    mouth = (j["leftEye"] + j["rightEye"]) / 2 + Vector((0.0, -0.012, -0.05))
    tilt = math.radians(35.0 + 8.0 * math.sin(math.pi * ease(t, timing[2] + 0.2, timing[3] - 0.2)))
    axis = Vector((0.0, math.sin(tilt), math.cos(tilt)))
    toward = Vector((0.0, math.cos(tilt), -math.sin(tilt)))
    at_mouth = mouth - (axis * 0.098 + toward * 0.046)
    q_mouth = a.frame_map(h, Z, Vector((-1.0, 0.0, 0.0)), axis)
    # Le déplacement de la tasse : du repos à la bouche (position et rotation mélangées).
    q = Quaternion().slerp(q_mouth, lift)
    now = base.lerp(at_mouth, lift)
    move = rigid(base, now, q)
    # La main : tenue sur l'anse (déplacée avec la tasse) ; avant la prise et après, de sa place vers la prise.
    rest = a.copy(f)
    a.rest_arms(desk, rest, t, period, which=("right",))
    w_rest, q_rest = arm_state(desk, rest, "right")
    hand_grasp = Matrix.Translation(grasp_wrist) @ hand_world(desk, "right", grip_q).to_matrix().to_4x4()
    held = move @ hand_grasp
    held_wrist = held.translation
    held_q = hand_delta(desk, "right", held.to_quaternion())
    pre = grasp_wrist - fingers * 0.04 + Vector((0.0, 0.0, 0.03))
    k = reach
    if lift > 0.0 or (timing[1] <= t <= timing[4]):
        wrist, hq = held_wrist, held_q
    else:
        # Vers la prise : d'abord au-dessus et en retrait de l'anse, puis les doigts glissent dedans.
        approach = ease(t, timing[0], timing[1] - 0.25) if t < timing[1] else 1.0 - ease(t, timing[4] + 0.25, timing[5])
        into = ease(t, timing[1] - 0.3, timing[1]) if t < timing[1] else 1.0 - ease(t, timing[4], timing[4] + 0.3)
        wrist = w_rest.lerp(pre, approach).lerp(grasp_wrist, into)
        hq = q_rest.slerp(grip_q, approach)
    elbow = Vector((-0.17, -0.06, 0.74)).lerp(Vector((-0.12, -0.16, 0.70)), lift)
    a.arm_ik(desk, f, "right", wrist, elbow, None, None, hand_rot=hq)
    grab = ease(t, timing[1] - 0.25, timing[1]) * (1.0 - ease(t, timing[4], timing[4] + 0.2))
    if grab > 0.0:
        handle_curl(desk, "right", grab)(f)
    else:
        a.relaxed(desk, f, "right")
    eye = base.lerp(mouth + Vector((0.0, -0.3, 0.0)), lift)
    a.look(desk, f, eye if t < timing[4] + 0.3 else a.MONITOR["center"].lerp(eye, 1.0 - ease(t, timing[4] + 0.3, timing[5])))
    hold = 0.5 if timing[1] <= t < timing[4] else 0.0
    return f, {"mug": move}, {"Hold": hold}


# --- le stylo ------------------------------------------------------------------------------------------------------
def pen_pinch(desk, side, center, axis):
    """La main qui pince un stylo couché (centre, axe) : doigts en travers du stylo, vers l'avant, paume vers le bas."""
    a = ad()
    across = Vector((axis.y, -axis.x, 0.0)).normalized()
    if across.y > 0.0:
        across = -across                       # vers l'avant (elle regarde −Y)
    fingers = (across + Vector((0.0, 0.0, -0.8))).normalized()
    sx = 1.0 if side == "left" else -1.0
    q = a.hand_rotation(desk, side, fingers, Vector((-sx * 0.2, 0.0, -1.0)))
    off = grip_offset(desk, side, q, pinch_curl(desk, side), pinch_point(desk, side))
    return q, center + Vector((0.0, 0.0, 0.004)) - off, fingers


def desk_take(desk, t, period):
    """
    Prendre son stylo (posé sur le carnet) de la main droite — jouée en miroir : la gauche —, le regarder dans sa main, le
    reposer exactement où il était.
    """
    a = ad()
    pen = desk.geo.features("type")["pen"]
    center, axis = mirror_v(pen["center"]), mirror_v(pen["axis"])
    q_grasp, grasp_wrist, fingers = pen_pinch(desk, "right", center, axis)
    timing = (0.4, 1.2, 1.9, 3.4, 4.1, 4.7)
    f = a.copy(desk.seated)
    breathe = math.sin(2 * math.pi * 2 * t / period)
    reach = ease(t, timing[0], timing[1]) * (1.0 - ease(t, timing[4], timing[5]))
    show = ease(t, timing[1] + 0.15, timing[2]) * (1.0 - ease(t, timing[3], timing[4] - 0.05))
    a.lean(f, 12.0 + 0.6 * breathe + 4.0 * reach * (1.0 - show), turn_deg=-6.0)
    a.rest_arms(desk, f, t, period, which=("left",))
    rest = a.copy(f)
    a.rest_arms(desk, rest, t, period, which=("right",))
    w_rest, q_rest = arm_state(desk, rest, "right")
    # Regarder le stylo : la main ramenée devant elle, tournée paume vers le haut.
    view = Vector((-0.05, -0.24, 0.90))
    q_view = a.hand_rotation(desk, "right", Vector((0.35, -0.85, 0.3)), Vector((0.2, 0.35, 0.9)))
    hand_grasp = Matrix.Translation(grasp_wrist) @ hand_world(desk, "right", q_grasp).to_matrix().to_4x4()
    if timing[1] <= t <= timing[4]:
        wrist = grasp_wrist.lerp(view, show)
        hq = q_grasp.slerp(q_view, show)
    else:
        approach = ease(t, timing[0], timing[1] - 0.2) if t < timing[1] else 1.0 - ease(t, timing[4] + 0.2, timing[5])
        pre = grasp_wrist + Vector((0.0, 0.0, 0.035))
        down = ease(t, timing[1] - 0.25, timing[1]) if t < timing[1] else 1.0 - ease(t, timing[4], timing[4] + 0.25)
        wrist = w_rest.lerp(pre, approach).lerp(grasp_wrist, down)
        hq = q_rest.slerp(q_grasp, approach)
    a.arm_ik(desk, f, "right", wrist, Vector((-0.20, -0.10, 0.75)), None, None, hand_rot=hq)
    grab = ease(t, timing[1] - 0.25, timing[1]) * (1.0 - ease(t, timing[4], timing[4] + 0.2))
    pinch_curl(desk, "right", 0.25 + 0.75 * grab)(f)
    # Le stylo : tenu tel qu'il a été pris (il suit la main), sinon à sa place.
    hand_now = Matrix.Translation(rig_hand(desk, f, "right").translation) @ rig_hand(desk, f, "right").to_quaternion().to_matrix().to_4x4()
    move = hand_now @ hand_grasp.inverted() if timing[1] <= t < timing[4] else Matrix.Identity(4)
    target = a.MONITOR["center"].lerp(center, ease(t, timing[0] - 0.3, timing[1] - 0.2)).lerp(view, show)
    target = target.lerp(a.MONITOR["center"], ease(t, timing[4], timing[5] + 0.2))
    a.look(desk, f, target, neck_share=0.4)
    hold = 0.5 if timing[1] <= t < timing[4] else 0.0
    return f, {"pen": move}, {"Hold": hold}


def rig_hand(desk, f, side):
    return desk.rig.fk(f)[desk.rig.hmap[f"{side}Hand"]]


def write_geometry(desk):
    """Le carnet et le stylo en position d'écriture : centre du dessus, axes (vers le haut de la page, vers sa droite)."""
    feat = desk.geo.features("write")
    nb = feat["notebook"]["center"]
    pen = feat["pen"]
    up = Vector((pen["axis"].x, pen["axis"].y, 0.0)).normalized()
    if up.y > 0.0:
        up = -up                                 # le haut de la page : loin d'elle
    right = Vector((up.y, -up.x, 0.0))           # sa droite sur la page
    if right.x > 0.0:
        right = -right
    return nb, up, right, pen


def write_pose(desk, t, period):
    """La pose d'écriture à l'instant t (la même que desk_write) : (image, pointe du stylo)."""
    a = ad()
    nb, up, right, _ = write_geometry(desk)
    f = a.copy(desk.seated)
    breathe = math.sin(2 * math.pi * 2 * t / period)
    a.lean(f, 18.0 + 0.6 * breathe, turn_deg=4.0, side_deg=-2.0)
    line_t = (t % (period / 2)) / (period / 2)
    k = line_t / 0.8 if line_t < 0.8 else 1.0 - (line_t - 0.8) / 0.2
    k = max(0.0, min(1.0, k))
    row = 0.0 if t < period / 2 else 0.018
    lift = 0.0 if line_t < 0.8 else math.sin(math.pi * (line_t - 0.8) / 0.2) * 0.012
    loops = up * (math.cos(t * 12.0) * 0.003) + right * (math.sin(t * 15.0) * 0.004) + Z * (max(0.0, math.sin(t * 9.0)) * 0.002)
    tip = nb + right * (-0.045 + 0.10 * k) + up * (0.03 - row) + Z * (0.002 + lift) + loops
    fingers = (up * 1.0 - right * 0.35 + Vector((0.0, 0.0, -0.55))).normalized()
    palm = (-right * 0.55 + Vector((0.0, 0.0, -0.8))).normalized()
    wrist = tip - fingers * 0.085 + right * 0.02 + Vector((0.0, 0.0, 0.03))
    a.arm_ik(desk, f, "right", wrist, Vector((-0.20, -0.12, 0.76)), fingers, palm)
    a.curl(desk, f, "right", {"Index": (28, 24, 18), "Middle": (38, 34, 20), "Ring": (55, 50, 25), "Little": (60, 52, 25)},
           thumb=(30.0, 18.0, 10.0), spread=0.0)
    # La gauche à plat sur la partie gauche du carnet (la tasse attend à côté).
    lw = nb - right * 0.045 - up * 0.02 + Vector((0.0, 0.0, 0.028))
    a.arm_ik(desk, f, "left", lw, Vector((0.18, -0.12, 0.75)), (up + right * 0.6).normalized() + Vector((0.0, 0.0, -0.1)), Vector((0.1, 0.0, -1.0)))
    a.relaxed(desk, f, "left", 0.6)
    a.look(desk, f, tip, neck_share=0.45)
    return f, tip


def pen_box(center, axis):
    """Le repère d'un stylo : à son centre, z le long de son axe."""
    return Matrix.Translation(center) @ Z.rotation_difference(axis).to_matrix().to_4x4()


def writing_box(desk, f):
    """Le repère du stylo tenu pour écrire (atelier_desk.stylus : entre le pouce et l'index, la pointe vers la page), z
    tourné vers le haut du stylo."""
    return ad().stylus(desk, f)


def pen_rest_box(desk):
    """Le stylo à sa place sur le carnet (position d'écriture), son axe orienté comme dans la main qui écrit (z vers le
    haut du stylo) : le passage de l'un à l'autre fait le plus petit tour."""
    _, _, _, pen = write_geometry(desk)
    fw, _ = write_pose(desk, 0.0, 8.0)
    z_write = writing_box(desk, fw).to_3x3() @ Z
    axis = pen["axis"] if pen["axis"].dot(z_write) >= 0.0 else -pen["axis"]
    return pen_box(pen["center"], axis)


def desk_write(desk, t, period):
    """Écrire dans le carnet : la main gauche le tient, la droite trace des lignes ; le regard suit le stylo."""
    f, _ = write_pose(desk, t, period)
    return f, {"pen": writing_box(desk, f) @ pen_rest_box(desk).inverted()}, {"Hold": 1.0}


def write_transition(desk, t, period, starting):
    """
    Prendre le stylo sur le carnet pour écrire (starting) ou le reposer en finissant : la main droite le pince là où il
    est couché, le soulève et le prend en main pour écrire (ou l'inverse) ; la gauche vient tenir le carnet (ou retourne
    sur sa cuisse).
    """
    a = ad()
    nb, up, right, pen = write_geometry(desk)
    q_grasp, grasp_wrist, _ = pen_pinch(desk, "right", pen["center"], pen["axis"])
    # La pose d'écriture du début de la boucle (desk_write, t = 0).
    fw, _ = write_pose(desk, 0.0, 8.0)
    w_write, q_write = arm_state(desk, fw, "right")
    lw_write, lq_write = arm_state(desk, fw, "left")
    # La pose de repos (les mains sur les cuisses, comme après le pivot de la chaise).
    fl = a.copy(desk.seated)
    a.lean(fl, 6.0)
    a.lap_hands(desk, fl, 0.0, 8.0)
    w_lap, q_lap = arm_state(desk, fl, "right")
    lw_lap, lq_lap = arm_state(desk, fl, "left")
    tt = t if starting else period - t
    reach, grasp, lifted = 0.55, 0.85, 1.45      # (temps « à l'endroit » : prendre)
    f = a.copy(desk.seated)
    k_body = ease(tt, 0.15, grasp)
    a.lean(f, 6.0 + 14.0 * k_body - 2.0 * ease(tt, grasp, lifted), turn_deg=4.0 * k_body, side_deg=-2.0 * k_body)
    pre = grasp_wrist + Vector((0.0, 0.0, 0.04))
    if tt < grasp:
        go = ease(tt, 0.05, reach)
        down = ease(tt, reach - 0.1, grasp)
        wrist = arc(w_lap, pre, go).lerp(grasp_wrist, down)
        hq = q_lap.slerp(q_grasp, go)
    else:
        k = ease(tt, grasp + 0.1, lifted)
        wrist = grasp_wrist.lerp(w_write, k)
        hq = q_grasp.slerp(q_write, k)
    # Le coude : bas, contre le flanc, mains sur les cuisses (là, le bord du bureau passe juste devant son épaule droite),
    # puis en avant pour écrire.
    k_arm = ease(tt, 0.05, reach)
    a.arm_ik(desk, f, "right", wrist, Vector((-0.17, 0.0, 0.66)).lerp(Vector((-0.20, -0.12, 0.76)), k_arm), None, None, hand_rot=hq)
    pinch = ease(tt, grasp - 0.25, grasp)
    write_k = ease(tt, grasp + 0.1, lifted)
    if write_k > 0.0:
        a.curl(desk, f, "right", {"Index": (30 - 2 * write_k, 35 - 11 * write_k, 15 + 3 * write_k),
                                  "Middle": (35 + 3 * write_k, 45 - 11 * write_k, 20), "Ring": (45 + 10 * write_k, 50, 20 + 5 * write_k),
                                  "Little": (50 + 10 * write_k, 50 + 2 * write_k, 20 + 5 * write_k)},
               thumb=(35 - 5 * write_k, 20 - 2 * write_k, 10), spread=0.0)
    else:
        pinch_curl(desk, "right", 0.3 + 0.7 * pinch)(f)
    kl = ease(tt, 0.3, lifted)
    a.arm_ik(desk, f, "left", arc(lw_lap, lw_write, kl), Vector((0.17, 0.0, 0.66)).lerp(Vector((0.18, -0.08, 0.72)), kl), None, None,
             hand_rot=lq_lap.slerp(lq_write, kl))
    a.relaxed(desk, f, "left", 0.8 - 0.2 * kl)
    a.look(desk, f, pen["center"].lerp(nb, ease(tt, grasp, lifted)), neck_share=0.45)
    # Le stylo : posé, puis tenu tel qu'il a été pris, puis glissé dans la prise d'écriture (celle de desk_write).
    hand_grasp = Matrix.Translation(grasp_wrist) @ hand_world(desk, "right", q_grasp).to_matrix().to_4x4()
    rest_box = pen_rest_box(desk)
    if tt >= grasp:
        hm = rig_hand(desk, f, "right")
        hand_now = Matrix.Translation(hm.translation) @ hm.to_quaternion().to_matrix().to_4x4()
        held = hand_now @ hand_grasp.inverted() @ rest_box
        hold = 0.5 + 0.5 * write_k
        if write_k > 0.0:
            box = writing_box(desk, f)
            held = Matrix.Translation(held.translation.lerp(box.translation, write_k)) @ \
                held.to_quaternion().slerp(box.to_quaternion(), write_k).to_matrix().to_4x4()
        move = held @ rest_box.inverted()
    else:
        move = Matrix.Identity(4)
        hold = 0.0
    return f, {"pen": move}, {"Hold": hold}


def desk_write_start(desk, t, period):
    return write_transition(desk, t, period, True)


def desk_write_end(desk, t, period):
    return write_transition(desk, t, period, False)
