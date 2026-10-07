# 0061 — Les fournisseurs d'images

**Contexte.** Le 2026-10-04, la propriétaire a demandé que Mika puisse générer des images : avec un modèle local
qu'elle fait tourner sur sa machine (Qwen-Image 2.1 en GGUF, servi par un paquet autonome à venir), et avec les API
les plus connues, OpenAI d'abord, « à la manière des LLM ». Rien ne générait d'images ; le seul sens visuel était la
caméra (décrire, jamais produire). Les API d'images diffèrent plus que celles du texte : OpenAI n'accepte que trois
tailles, un serveur local tout multiple de 64 ; certaines savent partir d'images de référence, d'autres non ; un
service hébergé refuse certains contenus et en modère d'autres, un serveur à soi non ; l'une répond en base64,
l'autre par une adresse qui expire. Sans abstraction, chaque fournisseur aurait fui dans ce qui demande une image.

**Décision.**

1. *Un port, comme pour les modèles de langage.* `ports/imaging.py` : une demande (`ImageRequest` : rôle, prompt,
   **proportion** et **qualité**, jamais des pixels ; images de référence ; prompt négatif et graine, ignorés par qui
   ne sait pas ; voie et priorité), ce qu'un fournisseur sait faire (`ImageCaps` : retoucher, combien de références,
   fond transparent, contenu pour adultes, local), un résultat (`ImageResult` : issue, images, raison en français,
   taille et qualité réellement demandées, prompt réécrit, jetons, coût). Trois rôles : `draw` (un dessin demandé),
   `edit` (retoucher une image reçue), `own` (ses dessins à elle, en fond) ; les deux derniers retombent sur `draw`.
2. *Une passerelle, `adapters/imaging/`, sur le modèle de `adapters/llm/`* : fournisseurs déclarés, rôles routés,
   repli de fournisseur en fournisseur (une chaîne, sans boucle, quatre au plus), créneaux à priorité — désormais
   partagés dans `kernel/slots.py` (`PrioritySlots`, `PREEMPTED`), un réservé au premier plan dès deux ; à un seul
   (un serveur local), la conversation interrompt un dessin de fond —, délai par voie (conversation 900 s, fond
   1800 s, attente comprise : une image soignée prend dix minutes sur le serveur local), une trace par appel. Trois règles que le texte n'a pas :
   - **les capacités d'abord** : seuls les candidats qui savent servir la demande sont appelés ; aucun ne le sait,
     `unsupported`, sans appel. Une demande pour adultes ne va qu'à un fournisseur qui l'accepte (`ImageCaps.adult`,
     déclaré seulement pour un serveur compatible : OpenAI ne l'est jamais) ;
   - **un refus n'est pas une panne** : la modération d'un service hébergé est une réponse, jamais redemandée à un
     autre service hébergé (ce serait chercher le plus permissif). Une demande qui le permet
     (`refusal_fallback`) peut repartir vers un serveur **local** de la chaîne, et lui seul ;
   - **une panne, une réponse vide ou un délai** passent au candidat suivant avec le temps qui reste.
   La passerelle ne lève pas : chaque demande rend un `ImageResult` (`ok`, `refused`, `failed`, `timeout`,
   `unsupported`, `unconfigured`) ; seule une annulation se propage.
3. *Deux types de fournisseur pour commencer* (`openai_images.py`, en HTTP direct, sans SDK) : **OpenAI** — la
   famille du modèle décide des paramètres (`gpt-image-*` : trois tailles, low/medium/high, jusqu'à 16 références,
   fond transparent, modération réglable, jetons comptés ; `dall-e-3`, `dall-e-2`) — et **compatible OpenAI** : tout
   serveur qui parle `/v1/images/generations` (le paquet local à venir, sd-server, LocalAI, un proxy), local quand son
   adresse l'est, gratuit. Une réponse en adresse est téléchargée tout de suite, bornée (25 Mo) ; un octet qui n'est
   pas une image est une panne ; la clé ne paraît dans aucun message, même renvoyée par le fournisseur. Le prompt
   ne transporte jamais les paramètres cachés que stable-diffusion.cpp lit dans un prompt
   (`<sd_cpp_extra_args>{…}</sd_cpp_extra_args>` : taille, nombre d'images) : le mot est effacé jusqu'à disparaître
   (`clean_prompt`), sinon un prompt influencé par quelqu'un pourrait épuiser la machine.
   Un troisième type, **stable-diffusion.cpp** (`sdcpp.py`), parle l'API native de `sd-server` : une tâche suivie
   jusqu'à son terme, annulée côté serveur quand Mika n'en veut plus (seulement si elle attend encore : une
   génération commencée va au bout), des pas par qualité (16 / 25 / 40, réglables : en dessous de 25, la grille
   fine de Qwen-Image 2.1 sous stable-diffusion.cpp revient), prompt négatif, graine, images
   de référence (retouche, quatre au plus), aucune métadonnée dans le PNG, un fond transparent demandé dans la forme
   que recommande Qwen-Image 2.1. L'API native ne lit pas de paramètres cachés, mais le prompt et le prompt négatif
   passent quand même par `clean_prompt` : la garantie ne dépend pas de la version de `sd-server`. D'autres (Gemini)
   s'ajoutent par un adaptateur chacun.
6. *Le serveur local est un paquet autonome hors de backendv2* (`services/mika-images/`, sans Python) :
   `sd-server` de stable-diffusion.cpp en construction Vulkan épinglée (aucune compilation, ni CUDA ni torch), les
   poids de Qwen-Image 2.1 et de son encodeur Qwen3-VL 8B en Q8_0 (Q4_K_M en variante plus rapide) et de son VAE
   vérifiés par empreinte, tout sur
   `/mnt/games/mika-images` ; une socket systemd utilisateur le démarre à la première demande et un relais
   (`systemd-socket-proxyd --exit-idle-time`) l'arrête après 10 minutes sans connexion — RAM et VRAM rendues. La
   RTX est choisie par son nom (ggml compte aussi le GPU intégré, et pas dans l'ordre de `vulkaninfo`). Mesuré sur
   une RTX 3060 : 137 s pour 1024² en 25 pas avec `easycache` (245 s en 20 pas sans), 57 s pour un brouillon par
   Mika. L'ordonnanceur `simple` est le défaut du serveur : avec celui que stable-diffusion.cpp choisit pour ce
   modèle, l'image porte une grille fine de 8 px et des bandes de 128 px (issue sd.cpp #2041 ; score mesuré à
   graine fixe 10,3 → 1,5). Le défaut privilégie la qualité : Q8, 40 pas, sans cache — 593 s en 1536×864. Le VAE
   « texture-fix » (décodeur réentraîné, même espace latent) n'a rien changé de visible à graine égale (écart moyen
   2,3/255) : il reste une option.
4. *Désactivée tant que rien n'est branché.* Sans fournisseur, la génération d'images n'existe pas
   (`LiveImaging.configured` faux, toute demande `unconfigured`). Le premier fournisseur déclaré sert `draw`
   d'office, comme « répondre » pour les modèles. Configuration › Intelligence › Images (fournisseurs, « Qui dessine
   quoi ») ; clés scellées dans `mind.db` (`Settings.imaging`) ; rechargée à chaud ; retirer un fournisseur emporte
   ses rôles et les replis qui menaient à lui. `mika images show|backend|route|remove|essai` : l'essai génère une
   image avec la configuration enregistrée et l'écrit dans un fichier.
5. *Ce que coûte une image* (`pricing.py`) : au jeton pour `gpt-image-*` (le décompte vient de l'API), à l'image
   pour `dall-e-*` ; un identifiant ne prend un tarif que s'il est la clé ou la clé datée — jamais par simple préfixe
   (`gpt-image-1.5` n'hérite pas de `gpt-image-1`) ; un modèle inconnu est compté 0 $ et dit une fois. Chaque appel
   rejoint le registre des appels (`CallLog`) sous le rôle `image.<rôle>` : son coût s'ajoute à celui des modèles.

**Conséquences.** La passerelle vivante est le port `imaging` du noyau : une faculté ou un plugin la lira par
`ctx.ports`, jamais par un adaptateur. Rien ne la consomme encore : le plugin qui fait dessiner Mika (un outil, une
capacité exécutée après commit, les événements, la garde des personnes autorisées, le rangement des images hors du
journal et leur oubli, l'envoi au frontend) est l'étape suivante. `ports.llm.PREEMPTED`
est désormais celui de `kernel/slots.py` (même texte). Épreuves : `tests/contract/test_imaging_openai.py`,
`tests/contract/test_imaging_sdcpp.py`, `tests/unit/test_imaging_gateway.py`, `tests/unit/test_imaging_config.py`,
`tests/protocol/test_console_images.py` ;
cinq règles cassées exprès (le refus, l'adulte, le premier fournisseur, la clé dans un message, le tarif par préfixe)
font chacune échouer leur test.
