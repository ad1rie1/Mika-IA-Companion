# 0096 — Une réflexion apaise, ce n'est pas un exploit

**Contexte.** Une pensée qui pèse (ce qu'une amie lui a confié, une croyance qu'elle a dû réviser) devient une
réflexion (« Repenser à ce que « Adrien » m'a confié », ADR 0053). Menée au bout, elle était vécue comme n'importe
quel but accompli : de la fierté, de l'estime en plus (selon l'effort), et une réussite de plus dans « tu mènes au bout
ce que tu entreprends » (ADR 0088). L'inquiétude pour quelqu'un devenait un trophée.

**Décision.** `goals.reflective(origin, source)` reconnaît une réflexion (origine `exchange` ou `revision` ; dans un
journal d'avant, une pensée pour source). `goals.closed` porte désormais l'origine du but. Une réflexion menée au
bout :
- apaise (`relieved`, cause `reflected` : « Ça vient d'avoir pris le temps de repenser à quelque chose qui te
  pesait ») ; si elle n'aboutissait pas, ça resterait un peu lourd (`melancholic`), sans frustration ;
- ne touche pas son estime, ni dans un sens ni dans l'autre ;
- ne compte pas parmi ce qu'elle mène au bout (`self.knows`) ;
- se dit dans son journal comme telle : « tu as pris le temps de repenser à « … » » (un acte `reflected`).

Ce qu'elle entreprend pour de bon (une exploration née d'un intérêt, un projet) garde sa fierté et son estime.

**Conséquences.** `GoalClosed.origin` (défaut vide : un journal d'avant se lit par sa source) ; `self` v11. Le test
d'avant qui voulait de la fierté (`test_a_worry_becomes_a_goal_then_pride…`) dit désormais l'apaisement et une
estime inchangée. Cibles : `tests/unit/test_reflection_soothes.py` ; mutations rouges.
