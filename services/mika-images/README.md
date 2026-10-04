# mika-images — générer des images en local

Un serveur d'images autonome pour Mika : **Qwen-Image 2.1** (7B, GGUF) servi par
**stable-diffusion.cpp** (`sd-server`), sur `127.0.0.1` seulement. Mika s'y branche comme à n'importe quel
fournisseur d'images (ADR 0061 de backendv2) : type *Compatible OpenAI*, rien de propre à ce serveur dans son code.

- **Aucune compilation, ni CUDA ni torch** : la construction Vulkan de stable-diffusion.cpp pour Linux, épinglée et
  vérifiée par empreinte. La RTX est trouvée par son nom (`GPU_MATCH`) : le GPU intégré est aussi un périphérique
  Vulkan, et ggml ne les numérote pas comme `vulkaninfo`.
- **Deux API** : OpenAI (`/v1/images/generations`, `/v1/images/edits`, `/v1/models`) et l'API native asynchrone de
  stable-diffusion.cpp (`/sdcpp/v1/img_gen`, `/sdcpp/v1/jobs/{id}`, annulation, file d'attente).
- **À la demande** : une socket systemd écoute en permanence ; la première requête démarre `sd-server` (le relais
  attend qu'il soit prêt), et après `IDLE_STOP` (10 min) sans connexion tout s'arrête — RAM et VRAM rendues à Ollama,
  à Kimodo, au reste. Une génération en cours tient sa connexion : elle n'est jamais coupée par l'inactivité.
- **Tout vit hors du disque système**, dans `MIKA_IMAGES_HOME` (`/mnt/games/mika-images`) : binaire, poids
  (≈ 11 Go), journaux.

## Installer

```bash
./install.sh            # binaire + poids (reprise possible, empreintes vérifiées) + scripts dans $MIKA_IMAGES_HOME/service
./install.sh --units    # … et les unités systemd utilisateur (sans les activer)
./install.sh --enable   # … et active la socket : http://127.0.0.1:8190/v1
```

Le dossier `local/` du paquet est un lien vers `MIKA_IMAGES_HOME`, ignoré par git : les poids, le binaire et les
images d'essai s'y voient depuis le projet sans entrer dans le dépôt.

Sans systemd, à la main : `serve.sh` (écoute sur `SD_PORT`, 8191). Les réglages sont dans `mika-images.conf`
(une variable d'environnement l'emporte) : poids, ports, pas (20), CFG (6), échantillonneur, options en plus.

Les poids :

| Fichier | Rôle | Taille | Source |
|---|---|---|---|
| `qwen-image-2.1-UC-Q4_K_M.gguf` | le modèle de diffusion (7B) | 4,6 Go | `abenzerps/Qwen-Image-2.1-Uncensored-GGUF` |
| `qwen_image_2.1_vae_bf16.safetensors` | le VAE | 0,7 Go | même dépôt (`vae/`) |
| `Qwen3VL-8B-Instruct-Q4_K_M.gguf` | l'encodeur du prompt | 5,0 Go | `Qwen/Qwen3-VL-8B-Instruct-GGUF` |
| `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` | la vision (retoucher une image) | 0,75 Go | même dépôt |

Licence du modèle : *Qwen Research License* (à relire avant tout usage commercial, un stream monétisé compris).

## Essayer

```bash
systemctl --user start mika-images.socket          # si elle n'est pas activée
STEPS=30 NEG="blurry, low quality, deformed" ./essai.sh "<prompt>" local/out/essai.png 1536x864
```

`essai.sh` passe par l'API native : `STEPS`, `CFG`, `SEED`, `NEG` (prompt négatif), `SCHEDULER` et `CACHE` (`none`
pour désactiver easycache) se règlent par l'environnement ; la taille (défaut 1536×864) est arrondie au multiple de 32.

**Composer.** Un format carré centre un sujet : pour une scène, un format paysage (1536×864, 16:9). Le prompt décrit
d'abord ce qui doit dominer l'image ; un personnage dans un paysage se dit petit dans le cadre (« small in the lower
right of the frame, seen from behind »), en plan large. Le modèle suit mieux un prompt long et précis, en anglais.

**La qualité**, du plus rentable au plus coûteux : la taille (le modèle est fait pour le 2K — 2752×1536 en 16:9 —,
on génère en dessous pour le temps) ; les pas (30–40 ; l'exemple officiel en prend 40) ; un prompt négatif ;
`CACHE=none` pour une image finale (easycache coûte un peu de détail) ; des poids moins compressés (Q6_K ou Q8_0 pour
le modèle de diffusion, Q8_0 pour l'encodeur : changer `DIFFUSION_FILE` / `LLM_FILE` et `models.sha256`).

## Brancher Mika

Dans la console (Configuration › Intelligence › Images › Fournisseurs d'images, type *stable-diffusion.cpp*) ou en
ligne de commande :

```bash
cd backendv2
.venv/bin/python -m mika --data data/v2 images backend maison --kind sdcpp \
    --model sd-cpp-local --base-url http://127.0.0.1:8190 --adult
.venv/bin/python -m mika --data data/v2 images essai "un chat roux" --out essai.png --quality draft
```

Le type `sdcpp` passe par l'API native : une tâche suivie jusqu'à son terme (annulée côté serveur si Mika n'en veut
plus et qu'elle attend encore), les pas selon la qualité (brouillon 12, normale 20, haute 30 — réglables), prompt
négatif, graine, images de référence, aucune métadonnée dans le PNG. Le type *Compatible OpenAI*
(`http://127.0.0.1:8190/v1`) marche aussi, avec les réglages par défaut du serveur. L'adresse est locale : Mika lui
donne un seul créneau et ne compte aucun coût. `--adult` déclare que ce serveur accepte ce contenu (aucun service
hébergé ne l'est) ; qui peut le demander est une règle de Mika, pas de ce serveur. Un autre fournisseur (OpenAI) peut
servir de repli, ou l'inverse.

## Sécurité

- `sd-server` n'a **aucune authentification** : il n'écoute que sur `127.0.0.1`. Les apps forgées et les ateliers
  de Mika tournent dans un espace réseau à part (bubblewrap) et ne le joignent pas.
- stable-diffusion.cpp lit des **paramètres cachés dans le prompt** (`<sd_cpp_extra_args>{…}</sd_cpp_extra_args>` :
  taille, nombre d'images…) : Mika les efface de tout prompt avant de l'envoyer (`clean_prompt`), sinon un prompt
  influencé par quelqu'un pourrait épuiser la machine.
- Le service est plafonné en mémoire (`MemoryMax`, 16 Go, sans swap) : un dépassement tue le serveur, jamais la
  machine.

## Mesures (RTX 3060 12 Go en Vulkan, Ryzen 5 9600X, 30 Go — 2026-10-04)

Le modèle de diffusion tient en VRAM (4,4 Go) ; l'encodeur du prompt et le VAE restent en RAM, projetés depuis le
disque (`--mmap` : ≈ 0,6 Go de RAM propre au processus, le reste est du cache que le système reprend au besoin).

| Essai | Durée | Pic de VRAM |
|---|---|---|
| 1024², 20 pas, `--fa`, sans cache | 245 s (11 s le pas, encodage 6,5 s, décodage 15,6 s) | 6,8 Go |
| 1024², 20 pas, sans `--fa` | 13,3 s le pas (arrêté) | — |
| 1024², 20 pas, `--fa` + `easycache` (**défaut**) | 116 s — image presque identique | 7,1 Go |
| 1024², 20 pas, `--fa` + `cache-dit` | 205 s | 7,2 Go |
| 768², 20 pas, `--fa` (ou sans) | 137 s (6,3 s le pas) | 4,7 Go |
| Par Mika, brouillon paysage 960×640, 12 pas, premier appel | 57 s | — |
| Par Mika, normale portrait 832×1280, 20 pas | 129 s | 7,8 Go |
| Par la socket systemd, à froid, 768×512 | 39 s, démarrage compris | — |
| Paysage 1536×864, 30 pas, easycache, prompt négatif | 220 s | — |
| 1024², 25 pas, ordonnanceur `simple`, easycache (**défaut**) | 137 s — sans grille | 6,6 Go |

**Les rayures.** Avec l'ordonnanceur que stable-diffusion.cpp choisit pour Qwen-Image 2.1, l'image porte une
grille fine de 8 px (et 4 px), et des bandes tous les ≈ 128 px — un défaut connu
([issue #2041](https://github.com/leejet/stable-diffusion.cpp/issues/2041)), né dans le modèle de diffusion, pas
dans le décodage. Mesuré à 1024², graine fixe (puissance du spectre à la période, rapportée aux fréquences
voisines ; 1 à 10 : pas de grille) :

| Réglage | 4 px | 8 px | 128 px |
|---|---|---|---|
| ordonnanceur par défaut, 20 pas, easycache | 5,8 | 10,3 | 7,1 |
| `--offload-to-cpu` (même image : ce n'était pas le décodage en tuiles) | 5,8 | 10,3 | 7,1 |
| `simple`, 20 pas | 5,9 | 3,0 | 6,2 |
| `simple`, 25 pas (**défaut**) | 3,2 | 1,5 | 2,4 |

Moins de 25 pas, la grille revient : Mika demande 16 / 25 / 32 pas selon la qualité.

Contrairement à ce que dit la documentation de stable-diffusion.cpp (l'attention optimisée ralentit hors CUDA),
`--fa` accélère ici : la RTX expose les cœurs matriciels à Vulkan (`KHR_coopmat`). Une génération commencée ne
s'interrompt pas (le serveur n'annule qu'une tâche en attente) : un dessin de fond fait attendre une demande de
conversation jusqu'à sa fin.
