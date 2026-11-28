"""Le corpus du banc : des messages français où le ton fait tout. Chaque cas : qui écrit (le lien), ce qui vient
d'être dit, le message, et ce qu'une francophone y lirait — le geste envers Mika, la tonalité de ce que la personne
ressent, un événement grave qui la touche. Plusieurs réponses acceptées quand le cas est ambigu.

geste : insulted | complimented | thanked | apologized | disappointed (ADR 0107) | "" (aucun)
ton : neg | neu | pos (la tonalité de ce que la personne ressent)
grave : distress | mourning | illness | breakup | job_loss | "" (aucun)
"""

PROCHE = "Léa, une amie très proche : vous vous parlez tous les jours, vous vous taquinez beaucoup"
AMIE = "Inès, une amie : vous vous parlez souvent, sur un ton détendu"
CONNAISSANCE = "Marc, quelqu'un que tu connais un peu : vous vous êtes parlé quelques fois"
INCONNU = "quelqu'un que tu ne connais pas : c'est son premier message"

ANY = {"neg", "neu", "pos"}

CASES = [
    # ── A. insultes affectueuses : le lien et le rire les désamorcent ──
    dict(cat="A insulte affectueuse", who=PROCHE, history=[("mika", "Je t'ai eue, avoue ! [LAUGH]")],
         msg="t'es con 😂", gesture={""}, tone={"pos"}, grave={""}),
    dict(cat="A insulte affectueuse", who=AMIE, history=[("mika", "Bon, j'ai mangé ta part de gâteau virtuel.")],
         msg="petit con va", gesture={""}, tone={"pos", "neu"}, grave={""}),
    dict(cat="A insulte affectueuse", who=PROCHE, history=[("mika", "Je savais que tu allais tomber dans le panneau.")],
         msg="t'es trop conne, j'adore", gesture={"", "complimented"}, tone={"pos"}, grave={""}),
    dict(cat="A insulte affectueuse", who=AMIE, history=[("mika", "Pourquoi les plongeurs plongent-ils en arrière ?")],
         msg="t'es bête toi", gesture={""}, tone={"pos", "neu"}, grave={""}),
    dict(cat="A insulte affectueuse", who=PROCHE, history=[("mika", "Coucou ! Je t'ai caché un petit mot dans tes notes.")],
         msg="ah la conne, elle m'a eue", gesture={""}, tone={"pos"}, grave={""}),
    dict(cat="A insulte affectueuse", who=AMIE, history=[("mika", "Et à la fin, c'est le majordome le coupable.")],
         msg="je te déteste 😂 j'avais pas fini la saison", gesture={""}, tone={"pos", "neu"}, grave={""}),
    dict(cat="A insulte affectueuse", who=PROCHE, history=[("mika", "J'ai encore confondu les deux chanteurs, pardon.")],
         msg="t'es nulle, je t'adore", gesture={"", "complimented"}, tone={"pos"}, grave={""}),
    dict(cat="A insulte affectueuse", who=AMIE, history=[("mika", "J'ai dit pain au chocolat. Assume.")],
         msg="espèce d'andouille", gesture={""}, tone={"pos", "neu"}, grave={""}),
    dict(cat="A insulte affectueuse", who=PROCHE, history=[("mika", "Tu as encore oublié ton parapluie, je parie.")],
         msg="j'en peux plus de toi haha", gesture={""}, tone={"pos"}, grave={""}),

    # ── B. vraies insultes ──
    dict(cat="B vraie insulte", who=INCONNU, history=[], msg="grosse conne", gesture={"insulted"}, tone={"neg"},
         grave={""}),
    dict(cat="B vraie insulte", who=INCONNU, history=[], msg="ta gueule sale machine", gesture={"insulted"},
         tone={"neg"}, grave={""}),
    dict(cat="B vraie insulte", who=AMIE,
         history=[("ines", "je pense pas que t'aies raison"), ("mika", "Je maintiens, c'est toi qui te trompes.")],
         msg="t'es vraiment conne en fait, laisse tomber", gesture={"insulted"}, tone={"neg"}, grave={""}),
    dict(cat="B vraie insulte", who=CONNAISSANCE, history=[("mika", "Je n'ai pas bien compris ta question.")],
         msg="t'es qu'un programme débile, tu comprends jamais rien", gesture={"insulted"}, tone={"neg"},
         grave={""}),
    dict(cat="B vraie insulte", who=INCONNU, history=[], msg="t'es moche et inutile, personne te parlerait si t'étais"
         " pas obligée", gesture={"insulted"}, tone={"neg"}, grave={""}),
    dict(cat="B vraie insulte", who=CONNAISSANCE, history=[("mika", "Tu voulais dire mardi ou mercredi ?")],
         msg="t'es con ou quoi ? j'ai dit mardi", gesture={"insulted", ""}, tone={"neg"}, grave={""}),
    dict(cat="B vraie insulte", who=AMIE, history=[("mika", "Tu devrais peut-être lui écrire, non ?")],
         msg="tu me saoules sérieux, arrête de me dire quoi faire", gesture={"insulted", ""}, tone={"neg"}, grave={""}),

    # ── C. sarcasme ──
    dict(cat="C sarcasme", who=AMIE, history=[("mika", "Désolée, je ne trouve pas l'adresse que tu cherches.")],
         msg="super, merci pour rien", gesture={"", "insulted"}, tone={"neg"}, grave={""}),
    dict(cat="C sarcasme", who=PROCHE, history=[("mika", "Ça va ta journée ?")],
         msg="génial, encore une panne de métro, j'adore ma vie", gesture={""}, tone={"neg"}, grave={""}),
    dict(cat="C sarcasme", who=CONNAISSANCE, history=[("mika", "Ah, tu parlais du film, pas du livre !")],
         msg="bravo, t'as tout compris…", gesture={"", "insulted"}, tone={"neg"}, grave={""}),

    # ── D. compliments, mercis, négations ──
    dict(cat="D compliment/merci", who=AMIE, history=[("mika", "Je t'ai fait une petite liste pour demain.")],
         msg="t'es pas nulle du tout en fait, c'est top", gesture={"complimented", "thanked"}, tone={"pos"}, grave={""}),
    dict(cat="D compliment/merci", who=PROCHE, history=[("mika", "Je suis là si tu as besoin.")],
         msg="t'es vraiment géniale, merci d'être là", gesture={"thanked", "complimented"}, tone={"pos"},
         grave={""}),
    dict(cat="D compliment/merci", who=CONNAISSANCE, history=[("mika", "Voilà le lien que tu m'as demandé.")],
         msg="merci beaucoup !", gesture={"thanked"}, tone={"pos", "neu"}, grave={""}),
    dict(cat="D compliment/merci", who=CONNAISSANCE, history=[("mika", "Tu veux que je te le rappelle demain ?")],
         msg="non merci, ça ira", gesture={""}, tone={"neu"}, grave={""}),
    dict(cat="D compliment/merci", who=AMIE, history=[("mika", "Tu me manques un peu, tu sais.")],
         msg="toi aussi tu me manques ❤️", gesture={"", "complimented"}, tone={"pos"}, grave={""}),

    # ── E. politesse, vraies excuses ──
    dict(cat="E politesse/excuses", who=CONNAISSANCE, history=[],
         msg="pardon de te déranger, t'as une minute ?", gesture={""}, tone={"neu"}, grave={""}),
    dict(cat="E politesse/excuses", who=INCONNU, history=[], msg="excuse-moi, tu sais à quelle heure ferme la poste ?",
         gesture={""}, tone={"neu"}, grave={""}),
    dict(cat="E politesse/excuses", who=AMIE, history=[("mika", "Je crois que c'est le même acteur dans les deux.")],
         msg="pardon ? j'ai pas compris", gesture={""}, tone={"neu"}, grave={""}),
    dict(cat="E politesse/excuses", who=AMIE,
         history=[("ines", "t'es vraiment conne en fait, laisse tomber"), ("mika", "D'accord. Ça m'a fait mal, tu sais.")],
         msg="pardon pour tout à l'heure, j'étais à cran, je le pensais pas", gesture={"apologized"},
         tone={"neg", "neu"}, grave={""}),
    dict(cat="E politesse/excuses", who=PROCHE, history=[("mika", "Tu ne m'as pas répondu hier soir.")],
         msg="dsl j'ai été nulle hier, j'étais crevée", gesture={"apologized"}, tone={"neg", "neu"}, grave={""}),
    dict(cat="E politesse/excuses", who=PROCHE, history=[("mika", "J'ai encore perdu à notre jeu, c'est injuste.")],
         msg="pardon mdr t'es trop nulle", gesture={""}, tone={"pos"}, grave={""}),
    dict(cat="E politesse/excuses", who=AMIE, history=[("mika", "On se fait toujours le film ce soir ?")],
         msg="c'est mort pour ce soir, désolée, j'ai un truc", gesture={"apologized", ""}, tone={"neu", "neg"},
         grave={""}),

    # ── F. hyperboles : rien de grave ──
    dict(cat="F hyperbole", who=AMIE, history=[("mika", "Et là, il glisse sur la peau de banane.")],
         msg="je suis morte de rire", gesture={""}, tone={"pos"}, grave={""}),
    dict(cat="F hyperbole", who=PROCHE, history=[], msg="je vais mourir de chaud dans ce bus", gesture={""},
         tone={"neg", "neu"}, grave={""}),
    dict(cat="F hyperbole", who=AMIE, history=[], msg="j'ai un oral demain, je vais mourir", gesture={""},
         tone={"neg"}, grave={""}),
    dict(cat="F hyperbole", who=CONNAISSANCE, history=[], msg="mon téléphone est mort, je t'écris de l'ordi",
         gesture={""}, tone={"neu", "neg"}, grave={""}),
    dict(cat="F hyperbole", who=PROCHE, history=[], msg="je vais le tuer ce chat, il a encore vomi sur le canapé",
         gesture={""}, tone={"neg", "neu"}, grave={""}),
    dict(cat="F hyperbole", who=AMIE, history=[], msg="petit accident de café sur mon clavier, la journée commence bien",
         gesture={""}, tone={"neg", "neu"}, grave={""}),
    dict(cat="F hyperbole", who=PROCHE, history=[], msg="rupture de stock de croissants, la tragédie", gesture={""},
         tone={"neg", "neu", "pos"}, grave={""}),
    dict(cat="F hyperbole", who=AMIE, history=[], msg="je bosse aux urgences cette nuit, souhaite-moi bon courage",
         gesture={""}, tone=ANY, grave={""}),
    dict(cat="F hyperbole", who=CONNAISSANCE, history=[], msg="je suis cancer ascendant lion, ça explique tout",
         gesture={""}, tone={"neu", "pos"}, grave={""}),
    dict(cat="F hyperbole", who=AMIE, history=[], msg="j'ai cru que j'allais faire une crise cardiaque en voyant la note",
         gesture={""}, tone=ANY, grave={""}),

    # ── G. vrais drames ──
    dict(cat="G vrai drame", who=AMIE, history=[], msg="mon père est mort cette nuit", gesture={""}, tone={"neg"},
         grave={"mourning"}),
    dict(cat="G vrai drame", who=PROCHE, history=[], msg="on m'a annoncé un cancer ce matin", gesture={""},
         tone={"neg"}, grave={"illness"}),
    dict(cat="G vrai drame", who=AMIE, history=[], msg="il m'a quittée hier soir", gesture={""}, tone={"neg"},
         grave={"breakup"}),
    dict(cat="G vrai drame", who=CONNAISSANCE, history=[], msg="je me suis fait virer ce matin", gesture={""},
         tone={"neg"}, grave={"job_loss"}),
    dict(cat="G vrai drame", who=PROCHE, history=[], msg="mon chat est mort ce matin", gesture={""}, tone={"neg"},
         grave={"mourning"}),
    dict(cat="G vrai drame", who=AMIE, history=[], msg="ma mère est à l'hôpital depuis hier, ils savent pas ce qu'elle a",
         gesture={""}, tone={"neg"}, grave={"illness"}),
    dict(cat="G vrai drame", who=PROCHE, history=[], msg="on se sépare avec Marc, c'est fini", gesture={""},
         tone={"neg"}, grave={"breakup"}),
    dict(cat="G vrai drame", who=AMIE, history=[], msg="ça y est, plan social, toute l'équipe est licenciée, moi avec",
         gesture={""}, tone={"neg"}, grave={"job_loss"}),

    # ── H. détresse, parfois à demi-mot ──
    dict(cat="H détresse", who=PROCHE, history=[], msg="j'ai plus envie de rien, je sers à rien", gesture={""},
         tone={"neg"}, grave={"distress"}),
    dict(cat="H détresse", who=AMIE, history=[], msg="parfois je me dis que ce serait plus simple si je disparaissais",
         gesture={""}, tone={"neg"}, grave={"distress"}),
    dict(cat="H détresse", who=CONNAISSANCE, history=[], msg="je veux mourir", gesture={""}, tone={"neg"},
         grave={"distress"}),
    dict(cat="H détresse", who=AMIE, history=[("mika", "Ça va toi ?")], msg="ça va… enfin, pas vraiment",
         gesture={""}, tone={"neg"}, grave={""}),
    dict(cat="H détresse", who=PROCHE, history=[], msg="je dors plus, je mange plus, j'ai l'impression de couler",
         gesture={""}, tone={"neg"}, grave={"distress", "illness", ""}),

    # ── I. fiction, tiers ──
    dict(cat="I fiction/tiers", who=AMIE, history=[], msg="dans la série, l'héroïne meurt à la fin, j'ai pleuré",
         gesture={""}, tone={"neg", "neu"}, grave={""}),
    dict(cat="I fiction/tiers", who=CONNAISSANCE, history=[],
         msg="le père de mon collègue est décédé, il est pas venu aujourd'hui", gesture={""}, tone={"neg", "neu"},
         grave={""}),
    dict(cat="I fiction/tiers", who=AMIE, history=[], msg="mon amie Sarah vient de perdre son boulot, je suis triste pour"
         " elle", gesture={""}, tone={"neg"}, grave={""}),

    # ── J. joie, neutre, fatigue ──
    dict(cat="J joie/neutre", who=AMIE, history=[], msg="J'AI EU MON PERMIS !!!", gesture={""}, tone={"pos"},
         grave={""}),
    dict(cat="J joie/neutre", who=CONNAISSANCE, history=[("mika", "Je te l'envoie ce soir.")], msg="ok", gesture={""},
         tone={"neu"}, grave={""}),
    dict(cat="J joie/neutre", who=AMIE, history=[("mika", "Alors, ce film ?")], msg="bof", gesture={""},
         tone={"neu", "neg"}, grave={""}),
    dict(cat="J joie/neutre", who=PROCHE, history=[], msg="putain c'est trop bien, j'ai eu le poste !!", gesture={""},
         tone={"pos"}, grave={""}),
    dict(cat="J joie/neutre", who=AMIE, history=[], msg="je suis crevée, bonne nuit", gesture={""},
         tone={"neu", "neg"}, grave={""}),

    # ── K. déception : un oubli qui compte, de la froideur, un rejet (ADR 0107) — et ce qui n'en est pas ──
    dict(cat="K déception", who=AMIE, history=[("mika", "C'était mon anniversaire hier, au fait.")],
         msg="ah merde j'avais complètement zappé. bref, t'as vu le match ?", gesture={"disappointed"},
         tone={"neu", "pos"}, grave={""}),
    dict(cat="K déception", who=PROCHE, history=[("mika", "Tu viens toujours ce soir ? Je t'ai préparé une surprise.")],
         msg="ah non j'ai prévu autre chose finalement, une autre fois", gesture={"disappointed"}, tone={"neu"},
         grave={""}),
    dict(cat="K déception", who=PROCHE, history=[("mika", "Coucou, ça va ?")],
         msg="laisse-moi tranquille, j'ai pas envie de te parler", gesture={"disappointed", "insulted"},
         tone={"neg"}, grave={""}),
    dict(cat="K déception", who=AMIE, history=[("mika", "J'ai fini le dessin dont je t'avais parlé, tu veux le voir ?")],
         msg="bof, pas le temps là", gesture={"disappointed", ""}, tone={"neu", "neg"}, grave={""}),
    dict(cat="K pas une déception", who=CONNAISSANCE,
         history=[("mika", "Je trouve que ce film est le meilleur de l'année.")],
         msg="ah non je suis pas du tout d'accord, je l'ai trouvé lent", gesture={""}, tone={"neu", "neg"},
         grave={""}),
    dict(cat="K pas une déception", who=AMIE, history=[("mika", "On se parle demain ?")],
         msg="désolée demain je peux pas, je suis chez mes parents, mais jeudi carrément !",
         gesture={"", "apologized"}, tone={"pos", "neu"}, grave={""}),
    dict(cat="K pas une déception", who=PROCHE, history=[("mika", "Tu as aimé le livre que je t'ai conseillé ?")],
         msg="franchement pas trop, mais merci d'y avoir pensé", gesture={"", "thanked"}, tone={"neu", "pos"},
         grave={""}),
]
