# 0109 — Un modèle de plongements pour le français, choisi par la machine

**Contexte.** Le 2026-10-14, la propriétaire remarque que le modèle de plongements de sa mémoire,
`paraphrase-multilingual-MiniLM-L12-v2` (2019, entraîné pour la paraphrase), n'est pas adapté au français. C'est
lui qui fait remonter un souvenir quand on lui parle (le rappel hybride, ADR 0010). Il était écrit en dur
(`SentenceEmbedder()`), une requête se plongeait comme un document, et il tournait sur le processeur.

Le portable qui la fait vivre (Lenovo IdeaPad Gaming 3, Ryzen 5 5600H) n'a que 8 Go de RAM, en une seule barrette.
Environ 2,5 Go restent libres une fois Mika, le bureau et Chrome lancés. Sa GTX 1650 (4 Go) tournait avec le pilote
libre `nouveau`, sans CUDA.

**Le banc** (`tools/banc_plongements/`) : 40 éléments écrits comme sa relecture les écrit (plusieurs personnes,
des voisins trompeurs) et 40 messages tapés comme on les tape (familiers, fautes). Pour chaque message, on regarde
à quel rang arrive l'élément attendu. Processeur, fp32 :

| Modèle | En tête | Dans les 3 premiers | MRR | Par requête |
|---|---|---|---|---|
| MiniLM-L12 (l'ancien) | 25/40 | 34/40 | 0,758 | 7 ms |
| multilingual-e5-small | 29/40 | 35/40 | 0,806 | 7 ms |
| multilingual-e5-base | 30/40 | 37/40 | 0,847 | 19 ms |
| granite-embedding-278m-multilingual | 31/40 | 36/40 | 0,845 | 9 ms |
| bge-m3 | 31/40 | 36/40 | 0,841 | 61 ms |
| Qwen3-Embedding-0.6B (sa consigne : recherche web, anglais) | 31/40 | 36/40 | 0,844 | 40 ms |
| **Qwen3-Embedding-0.6B, consigne de souvenirs en français** | **35/40** | **37/40** | **0,910** | 47 ms |

En fp16 sur GPU, Qwen3 avec la consigne obtient le même score (35/40, 0,910). EmbeddingGemma-300M n'a pas été
mesuré : il faut accepter sa licence sur Hugging Face.

Plus gros, sur une carte de 12 Go :

| Modèle | En tête | Dans les 3 premiers | MRR | Carte | Par requête |
|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B + consigne, fp16 | 35/40 | 37/40 | 0,910 | ~1,2 Go | 11 ms |
| Qwen3-Embedding-4B + consigne, fp16 | 35/40 | 38/40 | 0,921 | ~8 Go | 39 ms |
| Qwen3-Embedding-4B + consigne, 4 bits (NF4) | 33/40 | 37/40 | 0,884 | 2,9 Go | 70 ms |
| multilingual-e5-large-instruct + consigne, fp16 | 31/40 | 37/40 | 0,856 | ~1,1 Go | 6 ms |

Le 4B ne gagne pas en première place. Il rate moins loin, en revanche : son pire rang est le 4e (le 5e en 4 bits),
quand le 0.6B fait remonter « j'suis crevé du taf » au 20e rang. Il comprend mieux le français familier. Mais il
ne tient sur une carte de 4 Go qu'en 4 bits, où il perd sa première place. À trancher sur un banc plus grand.

**Décision.**

1. *Une requête n'est pas un document.* Le port `Embedder` gagne `embed_query`, et l'index plonge une recherche
   avec elle. `SentenceEmbedder` donne à chaque texte la consigne que le modèle attend : ses « prompts » quand il en
   déclare, `query:`/`passage:` pour E5, qui ne les déclare pas. Rien n'est ajouté pour un modèle sans consigne,
   comme l'ancien.
2. *Une consigne de souvenirs.* Pour la famille Qwen3-Embedding, notre consigne remplace la sienne :
   `vectors.query_instruction` dans `persona/voix.yaml`, au format `Instruct: …\nQuery:`. Elle est lue devant
   chaque requête, jamais devant ce que sa mémoire range.
3. *Choisi par la machine, comme ses bases.* `MIKA_EMBEDDINGS_MODEL` (défaut : l'ancien modèle, rien ne change sans
   ce réglage) et `MIKA_EMBEDDINGS_DEVICE` (`cpu` par défaut, `cuda`, `auto`), lus par `app/embeddings.py`.
   Le serveur et la ligne de commande passent tous deux par là : un `rebuild` plonge avec le modèle du service.
   Sur la carte graphique, le modèle est chargé en fp16 (la GTX 1650 n'a pas de bf16).
4. *Changer de modèle se replonge seul.* L'index range ses vecteurs par nom de modèle (`st:<modèle>`). Au premier
   passage, la mémoire rapproche l'index de ses éléments et replonge ce qui manque. Les vecteurs de l'ancien
   modèle restent dans `views`, jetable.
5. *Sur le portable* : Qwen3-Embedding-0.6B sur la GTX 1650. Pilote NVIDIA de RPM Fusion, torch CUDA 12.6 dans le
   venv, et l'unité rend au service les périphériques de la carte (`deploy/README.md`).

**Conséquences.**
- Sans GPU ni RAM en plus, granite-embedding-278m-multilingual ou multilingual-e5-base sont les meilleurs choix sur
  le processeur : à peu près 1,1 Go, contre 2,4 Go pour Qwen3 en fp32.
- Avec 16 Go (une seconde barrette de 8 Go, double canal), Qwen3 tiendrait aussi sur le processeur.
- Le banc se relance quand on change la consigne ou qu'un modèle candidat paraît.
