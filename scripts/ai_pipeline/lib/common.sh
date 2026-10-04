#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions communes (logging, agent IA, prompts, notifications)
# ============================================================================

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# -- Codes de sortie de l'orchestrateur ---------------------------------------
# run.sh décidait de la suite en cherchant des phrases dans la sortie de
# l'orchestrateur (« Rien à faire », « Pipeline terminé avec succès »…) : une
# reformulation d'un message cassait la boucle sans que rien ne le signale. Le
# contrat est désormais le code de sortie.
EXIT_OK=0            # travail livré : PR, issues, PR rebasées
EXIT_FAIL=1          # échec
EXIT_NOTHING=10      # rien à faire : aucun module disponible, aucune issue en attente
EXIT_NO_RESULT=11    # passage fait, sans résultat : aucune modification, aucun constat
EXIT_BUSY=75         # une autre instance tient le verrou (EX_TEMPFAIL)

mkdir -p "$LOGS_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="${LOGS_DIR}/run-${TIMESTAMP}-$$.log"

# Le terminal reçoit les couleurs, le fichier du texte brut : les journaux
# étaient pleins de séquences `\033[0;34m` qui rendaient grep et less pénibles.
_emit() {
    local color="$1" tag="$2"; shift 2
    printf '%b%s%b %s\n' "$color" "$tag" "$NC" "$*"
    printf '%s %s\n' "$tag" "$*" >> "$LOG_FILE"
}
log()    { _emit "$BLUE"   "[$(date +%H:%M:%S)]" "$@"; }
ok()     { _emit "$GREEN"  "[OK]"   "$@"; }
warn()   { _emit "$YELLOW" "[WARN]" "$@"; }
err()    { _emit "$RED"    "[ERR]"  "$@"; }
header() {
    local bar="══════════════════════════════════════════"
    printf '\n%b%s\n  %s\n%s%b\n\n' "$CYAN" "$bar" "$*" "$bar" "$NC"
    printf '\n%s\n  %s\n%s\n\n' "$bar" "$*" "$bar" >> "$LOG_FILE"
}

# Garde les LOGS_KEEP journaux les plus récents. Chaque invocation de
# l'orchestrateur en crée un ; sans rotation le dossier en accumulait des
# centaines.
prune_logs() {
    local keep="${LOGS_KEEP:-200}"
    (( keep > 0 )) || return 0
    find "$LOGS_DIR" -maxdepth 1 -name 'run-*.log' -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | tail -n +$((keep + 1)) | cut -d' ' -f2- \
        | while IFS= read -r old; do rm -f -- "$old"; done
}

# Pause interruptible : un `sleep` au premier plan retient un SIGTERM envoyé au
# seul shell jusqu'à sa fin (30 min). Mis en arrière-plan puis attendu, il
# laisse le trap s'exécuter tout de suite.
pause_for() {
    sleep "$1" &
    wait $!
}

# Écrit une clé du compte rendu que run.sh relit (module choisi, etc.).
report_set() {
    [[ -n "${AI_PIPELINE_REPORT:-}" ]] || return 0
    printf '%s=%s\n' "$1" "$2" >> "$AI_PIPELINE_REPORT"
}

# ============================================================================
# Agent IA
# ============================================================================
ai_agent_label() {
    case "$AI_AGENT" in
        claude) echo "Claude Code" ;;
        codex)  echo "Codex CLI" ;;
        *)      echo "$AI_AGENT" ;;
    esac
}

ai_agent_timeout() {
    case "$AI_AGENT" in
        claude) echo "$CLAUDE_TIMEOUT" ;;
        codex)  echo "$CODEX_TIMEOUT" ;;
        *)      echo "$AI_AGENT_TIMEOUT" ;;
    esac
}

check_ai_agent_config() {
    case "$AI_AGENT" in
        claude|codex) ;;
        *)
            err "AI_AGENT invalide: '$AI_AGENT' (attendu: claude ou codex)"
            exit "$EXIT_FAIL"
            ;;
    esac
}

check_ai_cli() {
    check_ai_agent_config
    local cmd="$CLAUDE_CMD" name="Claude Code CLI"
    [[ "$AI_AGENT" == "codex" ]] && cmd="$CODEX_CMD" name="Codex CLI"
    command -v "$cmd" >/dev/null || {
        err "Prérequis manquant: $cmd ($name)"
        exit "$EXIT_FAIL"
    }
}

# Détecte une sortie d'agent IA causée par un rate limit / quota épuisé.
#
# Seule la FIN de la sortie compte : c'est là que le CLI écrit son erreur. Le
# texte entier contenait la réflexion de l'agent, et ce projet parle de quotas,
# de limites et de 429 dans son propre code — un agent qui échouait après avoir
# lu le routeur LLM était pris pour un agent rate-limité, et attendait 30 min.
_ai_output_is_rate_limit() {
    local output_file="$1"
    [[ -s "$output_file" ]] || return 1
    tail -n 40 "$output_file" | grep -qiE \
        "hit your (usage )?limit|usage limit reached|rate[ _-]?limit(ed)?|too many requests|\b429\b|credits? (exhausted|insufficient|exceeded)|insufficient_quota|quota (exceeded|reached)|exceeded your current quota|resets (at )?[0-9]"
}

# Exécute une seule fois la CLI de l'agent IA, depuis le répertoire courant
# (le worktree du pipeline). Pas de retry ici.
_run_ai_agent_once() {
    local mode="$1" prompt="$2" output_file="$3"
    local timeout_s
    timeout_s=$(ai_agent_timeout)

    case "$AI_AGENT" in
        claude)
            # --strict-mcp-config sans --mcp-config : aucun serveur MCP. Sans lui,
            # chaque appel démarrait ceux de l'utilisateur (Blender, Unity,
            # navigateur…) — lent, et des outils qu'aucune tâche n'a à toucher.
            # --no-session-persistence : des centaines de tâches automatiques ne
            # viennent plus remplir l'historique de sessions de l'utilisateur.
            local -a claude_args=(
                "$CLAUDE_CMD" -p "$prompt"
                --strict-mcp-config
                --no-session-persistence
                --no-chrome
            )
            if [[ "$mode" == "read" ]]; then
                claude_args+=(--allowedTools "Read,Glob,Grep")
            else
                claude_args+=(--allowedTools "Read,Edit,Write,Glob,Grep,Bash")
            fi
            [[ -n "$CLAUDE_MODEL" ]] && claude_args+=(--model "$CLAUDE_MODEL")
            # Budget de réflexion : --effort pilote le niveau, MAX_THINKING_TOKENS
            # pose un plafond dur en tokens. Vide = défaut de ~/.claude/settings.json.
            [[ -n "${CLAUDE_EFFORT:-}" ]] && claude_args+=(--effort "$CLAUDE_EFFORT")
            if [[ -n "${CLAUDE_MAX_THINKING_TOKENS:-}" ]]; then
                MAX_THINKING_TOKENS="$CLAUDE_MAX_THINKING_TOKENS" \
                    timeout "$timeout_s" "${claude_args[@]}" < /dev/null > "$output_file" 2>&1
            else
                timeout "$timeout_s" "${claude_args[@]}" < /dev/null > "$output_file" 2>&1
            fi
            ;;
        codex)
            local -a codex_args=(
                "$CODEX_CMD" exec
                --cd "$PWD"
                --color never
                --ephemeral
            )
            if [[ "$mode" == "read" ]]; then
                codex_args+=(--sandbox read-only)
            else
                codex_args+=(--full-auto)
            fi
            [[ -n "$CODEX_MODEL" ]] && codex_args+=(--model "$CODEX_MODEL")
            [[ -n "${CODEX_EFFORT:-}" ]] && codex_args+=(-c "model_reasoning_effort=\"$CODEX_EFFORT\"")
            timeout "$timeout_s" "${codex_args[@]}" "$prompt" < /dev/null > "$output_file" 2>&1
            ;;
    esac
}

# Wrapper : lance l'agent IA, et si la sortie indique un rate limit / quota,
# attend AI_RATE_LIMIT_RETRY_DELAY puis relance, jusqu'à AI_RATE_LIMIT_MAX_RETRIES.
# Retourne l'exit code de la dernière tentative (succès, vrai échec, ou rate
# limit persistant après épuisement des retries).
run_ai_agent() {
    local mode="$1" prompt="$2" output_file="$3"
    local label
    label=$(ai_agent_label)

    local attempt=0
    local max_retries="${AI_RATE_LIMIT_MAX_RETRIES:-0}"
    local delay="${AI_RATE_LIMIT_RETRY_DELAY:-1800}"
    local exit_code=0

    while : ; do
        exit_code=0
        _run_ai_agent_once "$mode" "$prompt" "$output_file" || exit_code=$?

        [[ $exit_code -eq 0 ]] && return 0

        # Ne pas retry sur un timeout (124) — c'est un vrai problème de durée,
        # pas un rate limit.
        [[ $exit_code -eq 124 ]] && return $exit_code

        # Vrai échec (auth, crash, etc.) → on remonte l'erreur immédiatement.
        _ai_output_is_rate_limit "$output_file" || return $exit_code

        if (( attempt >= max_retries )); then
            err "${label}: rate limit toujours présent après ${attempt} retry(s), abandon"
            return $exit_code
        fi

        attempt=$(( attempt + 1 ))
        local hint
        hint=$(tail -n 40 "$output_file" | grep -oiE "resets [0-9][0-9aApPmM:\. -]+(\([^)]+\))?" | head -1 || true)
        warn "${label}: rate limit détecté${hint:+ ($hint)} — attente ${delay}s avant retry ${attempt}/${max_retries}"
        notify_slack "AI Pipeline [WAIT] - ${label} rate-limited, retry ${attempt}/${max_retries} dans ${delay}s${hint:+ — $hint}"

        if ! pause_for "$delay"; then
            err "Attente interrompue, abandon des retries"
            return $exit_code
        fi
        log "Reprise après attente rate-limit (tentative ${attempt}/${max_retries})"
    done
}

# Sonde de disponibilité : 0 = l'agent répond (ou échoue pour une autre raison
# qu'un quota, on tente quand même), 1 = quota/rate limit.
#
# Une seule tentative, sans le retry de run_ai_agent : c'est à l'appelant de
# décider s'il attend (wait_for_ai_tokens) — la sonde pouvait sinon bloquer six
# heures avant de rendre la main. Effort minimal : demander « OK » ne justifie
# pas de payer le niveau de réflexion des tâches. Un succès vaut AI_PROBE_TTL
# secondes, partagé entre run.sh et les orchestrateurs qu'il lance.
check_ai_tokens() {
    check_ai_cli

    local label stamp="${LOGS_DIR}/.probe-ok"
    label=$(ai_agent_label)

    if [[ -f "$stamp" ]]; then
        local age=$(( $(date +%s) - $(stat -c %Y "$stamp" 2>/dev/null || echo 0) ))
        (( age < ${AI_PROBE_TTL:-600} )) && return 0
    fi

    local test_output test_exit=0
    test_output=$(mktemp)
    CLAUDE_EFFORT=low CODEX_EFFORT=low CLAUDE_MAX_THINKING_TOKENS="" \
        _run_ai_agent_once "read" "Réponds uniquement OK" "$test_output" || test_exit=$?

    if [[ $test_exit -ne 0 ]]; then
        if _ai_output_is_rate_limit "$test_output"; then
            rm -f "$test_output" "$stamp"
            err "Limite de tokens/crédits ${label} atteinte"
            return 1
        fi
        warn "${label} a échoué au test de disponibilité (exit $test_exit), tentative quand même"
        tail -5 "$test_output" 2>/dev/null || true
        rm -f "$test_output"
        return 0
    fi

    rm -f "$test_output"
    touch "$stamp"
    ok "Agent IA disponible: ${label}"
    return 0
}

# ============================================================================
# Contexte projet injecté dans TOUS les prompts IA
# ============================================================================
# Sans ce bloc, chaque audit redécouvre le projet de zéro et re-signale les
# mêmes décisions d'architecture délibérées comme si c'étaient des bugs. Il ne
# recopie pas l'architecture : il dit où elle est écrite, et ce qui ferait
# fausse route.
ai_project_context() {
    cat <<'CONTEXT'
## Le projet

Mika : un personnage d'IA compagne, présent en continu, avec un avatar 3D.

- `backendv2/` — le moteur VIVANT (paquet Python `mika`, sans Django). Une
  psyché à **journal d'événements** : tout ce qui lui arrive s'ajoute au
  journal, l'état de chaque faculté s'en déduit par des réducteurs purs. Couches
  (`kernel` → `vocab` → `ports` → `contracts` → `faculties`/`plugins`/`adapters`
  → `runtime` → `inspector`/`sim` → `app`), facultés (`memory`, `affect`,
  `identity`, `social`, `others`, `goals`, `projects`, `world`…), plugins
  (`email`, `forge`, `rss`, `camera`), console d'opérateur (`inspector`).
- `frontend/Web/` — client Vite + TypeScript + Three.js + VRM : rendu 3D,
  animation, TTS navigateur, lip-sync. Son protocole avec le backend est lu
  dans son propre code.
- `old/` — la v1 (Django) ARCHIVÉE. On ne la modifie pas, on ne la prend pas
  pour référence : son comportement n'est pas un oracle.
- Langues : identifiants de code en anglais ; prompts, interface, commentaires
  et documentation en français.

**Lis AVANT toute analyse : `backendv2/ARCHITECTURE.md`**, puis les ADR de
`backendv2/docs/adr/` qui touchent ton périmètre. Le `CLAUDE.md` à la racine
documente surtout la v1 archivée : il ne fait PAS foi pour `backendv2/`.

## Ce qui fait foi dans backendv2 — ne le « corrige » jamais

Un choix couvert par un ADR n'est pas un défaut. Les règles suivantes sont
vérifiées par `lint-imports` et `ruff` ; les contourner est une régression :

- **Une faculté n'importe jamais une autre faculté** ; elles se lisent par les
  faits (`kernel/facts.py`). Les adaptateurs n'importent ni facultés ni
  runtime ; ni le runtime ni l'inspecteur ne nomment une faculté. Pas d'import
  dans une fonction.
- **L'heure, le hasard et les identifiants sont injectés.** Une lecture directe
  de l'horloge (`datetime.now()`, `time.time()`), de `random` ou d'`uuid` hors
  des points d'injection EST un défaut — c'est l'inverse de la v1.
- **`except Exception` aveugle** : permis seulement dans `runtime/boundary.py`
  et les adaptateurs. Ailleurs, une exception avalée est un vrai défaut.
- **Un réducteur est pur et total** ; une charge utile d'événement porte des
  observations, des intentions, des deltas ou des tirages enregistrés — jamais
  un état recalculé. Un type d'événement appartient à son propriétaire, seul à
  l'émettre. Changer la forme d'une charge utile exige un *upcaster*, sinon le
  rejeu du journal existant casse.
- **Tout texte gardé déclare qui il concerne** (`Content`, ADR 0024) : l'oubli
  doit pouvoir l'atteindre.
- **Aucun effet ne part avant son commit** ; ce qui sort de la machine est une
  capacité, exécutée tout de suite ou après accord d'un opérateur.
- **Les garde-fous de la personne sont gradués, pas binaires** (divulgation,
  confidences, affect, fatigue) : remplacer une gradation par un interdit est
  une régression. La certitude sur *qui parle*, elle, reste mécanique.
- **Telegram fermé par défaut**, atelier et Forge sous bubblewrap **sans
  repli**, fournisseur Claude Code par **la CLI et son propre login** (jamais
  un jeton OAuth extrait) : délibérés.
- Un comportement se valide par une **cible d'intention** (ce qu'une personne
  ferait), jamais par parité avec la v1.

Si tu crois vraiment tenir un problème sur l'un de ces points, il te faut un
scénario de défaillance concret et reproductible — sinon, passe.
CONTEXT
}

# ============================================================================
# Politique de tests injectée dans TOUS les prompts IA
# ============================================================================
# Aucun workflow GitHub Actions n'existe sur ce dépôt : rien ne validera la PR
# après coup. Mais la suite complète est trop longue et trop gourmande (la
# machine a déjà été tuée par OOM sous plusieurs suites parallèles). D'où le
# compromis : vérification CIBLÉE obligatoire sur ce qu'on a touché, suite
# complète interdite.
#   ai_test_policy write  → modes fix / worker (l'agent peut modifier le code)
#   ai_test_policy read   → mode audit (lecture seule)
ai_test_policy() {
    local mode="${1:-write}"

    if [[ "$mode" == "read" ]]; then
        cat <<'POLICY'
## Politique de TESTS (règle ABSOLUE)

- N'exécute AUCUN test ni outil : ni `pytest`, ni `mika sim`, ni `npm test`, ni script de reproduction.
- Ne signale JAMAIS "tests manquants", "couverture insuffisante" ou "il faudrait un test de non-régression" : c'est hors périmètre de cet audit et ce type d'issue est systématiquement rejeté.
- La correction suggérée dans une issue doit porter sur le CODE, jamais sur l'ajout de tests.
POLICY
        return 0
    fi

    local policy
    policy=$(cat <<'POLICY'
## Politique de TESTS (règle ABSOLUE - coût, durée et mémoire)

Aucun CI ne relira ton travail : la vérification, c'est toi, puis un humain.
Mais la suite complète est hors de question. Tu vérifies donc CIBLÉ, et
seulement ce que tu as touché.

- N'exécute JAMAIS une suite complète : ni `pytest` nu, ni `pytest tests/`, ni `npm test`, ni `npx vitest run` sans fichier.
- N'exécute JAMAIS le simulateur (`mika sim run`) ni la sonde (`mika sim sonde` : elle appelle un vrai modèle, elle coûte).
- N'écris AUCUN nouveau fichier ni fonction de test, même "pour valider" ta correction. Aucune PR de ce pipeline n'a pour objet d'ajouter de la couverture.
- Ne crée PAS de script jetable de reproduction : relis le code à la place.
- Ne modifie un test existant QUE si ta correction le casse mécaniquement (signature ou API changée). Dans ce cas : adaptation minimale, jamais de réécriture.
- Vérification autorisée, une seule fois, à la fin. Tu travailles dans un worktree : le paquet `mika` de l'environnement pointe sur une AUTRE copie du code, d'où le `PYTHONPATH=src` obligatoire.
  - backendv2, depuis `backendv2/` :
    - `"@V2_VENV@/bin/ruff" check <fichiers modifiés>`
    - `PYTHONPATH=src "@V2_VENV@/bin/lint-imports"` (contrats de couches, rapide)
    - AU PLUS DEUX fichiers de test ciblés qui couvrent la zone touchée : `PYTHONPATH=src "@V2_VENV@/bin/python" -m pytest tests/unit/test_<zone>.py -x -q`
  - frontend, depuis `frontend/Web/` : `npx tsc --noEmit` (garde-fou dur, ne le saute pas si tu as modifié `frontend/Web/src/`), puis au plus un fichier ciblé : `npx vitest run <chemin/du/test>`.
- Si un test ciblé échoue à cause de ta modification, corrige ta modification. S'il échouait déjà avant, ne le touche pas et signale-le dans ton résumé.

Exception unique : si l'issue traitée demande EXPLICITEMENT d'ajouter ou de corriger un test, fais uniquement ce qui est demandé.
POLICY
)
    printf '%s\n' "${policy//@V2_VENV@/$V2_VENV}"
}

# Contraintes communes à tout mode qui modifie le code (fix, worker). La liste
# des fichiers protégés vient de FORBIDDEN_PATTERNS : elle était recopiée à la
# main dans chaque prompt, et avait divergé de celle que le pipeline vérifie.
ai_write_constraints() {
    local protected
    protected=$(printf '`%s`, ' "${FORBIDDEN_PATTERNS[@]}")
    protected="${protected%, }"
    cat <<CONSTRAINTS
## Contraintes ABSOLUES

1. Tu peux LIRE, MODIFIER des fichiers et exécuter des commandes bash, dans le répertoire courant uniquement.
2. Pour chaque correction, fais un commit séparé : \`git add <fichiers précis> && git commit -m "prefix: description"\`
   - Jamais \`git add -A\`, \`git add .\` ni \`git commit -a\` : n'ajoute que ce que tu as modifié.
   - Préfixes obligatoires : bug: / security: / feat: selon le type de correction
   - Message de commit en français
3. Tu ne dois JAMAIS exécuter : git push, git branch, git checkout, git switch, git merge, git rebase, git reset, git stash, git worktree
4. Tu ne dois JAMAIS exécuter de commandes système dangereuses (rm -rf, etc.)
5. Fichiers protégés, à ne JAMAIS modifier (motifs glob depuis la racine) : ${protected}. Si la correction l'exige, ne la fais pas : décris-la dans ton résumé, un humain l'appliquera.
6. Tu ne dois JAMAIS ajouter d'alias ni renommer une fonction existante
7. Chaque modification doit être minimale et ciblée, dans le style du code qui l'entoure
8. Respecte la politique de tests ci-dessous : pas de nouveaux tests, pas de suite complète, vérification ciblée uniquement
CONSTRAINTS
}

# Exécute une requête `gh` en distinguant « zéro résultat » de « la requête a
# échoué ».
#
# Le `2>/dev/null || echo ""` employé partout confondait les deux, et ça s'est
# vu en vrai : le dépôt a été renommé, l'API Search de GitHub ne suit pas les
# renommages (422) alors que REST et GraphQL les redirigent — donc la création
# d'issues fonctionnait pendant que `gh issue list --label`, qui passe par
# Search, renvoyait vide. Le worker annonçait « Aucune issue Propose_AI_PR en
# attente » avec 193 issues ouvertes, la boucle se déclarait stable et dormait
# 30 minutes. Faux, silencieux, et indiscernable du succès.
gh_query() {
    local out rc=0
    out=$("$@" 2>&1) || rc=$?
    if [[ $rc -ne 0 ]]; then
        err "Requête GitHub échouée (exit ${rc}) : $*" >&2
        echo "$out" | tail -3 >&2
        err "Pistes : 'gh auth status', et vérifier que le remote pointe sur le dépôt actuel (renommé ?)" >&2
        return "$rc"
    fi
    printf '%s' "$out"
}

# Vérifie les prérequis système. La copie de travail de l'utilisateur n'a plus
# besoin d'être propre : le pipeline travaille dans son propre worktree.
check_prerequisites() {
    local missing=()
    local tool
    for tool in git gh jq flock timeout; do
        command -v "$tool" >/dev/null || missing+=("$tool")
    done
    check_ai_cli

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Prérequis manquants: ${missing[*]}"
        exit "$EXIT_FAIL"
    fi

    if ! gh auth status &>/dev/null; then
        err "GitHub CLI non authentifié. Lancer: gh auth login"
        exit "$EXIT_FAIL"
    fi

    if [[ -z "${GH_REPO:-}" ]]; then
        err "Dépôt GitHub introuvable : le remote '${REPO_REMOTE}' de ${PROJECT_ROOT} ne pointe pas sur github.com"
        exit "$EXIT_FAIL"
    fi

    ok "Prérequis validés (dépôt ${GH_REPO})"
}

# Retranche du périmètre les sous-dossiers qui sont eux-mêmes des modules du
# pipeline (cf. MODULE_SCOPE_EXCLUDES). Silencieux si le module n'en a aucun.
module_scope_note() {
    local mod="$1"
    local excl="${MODULE_SCOPE_EXCLUDES[$mod]:-}"
    [[ -z "$excl" ]] && return 0
    echo "Hors périmètre pour ce module : ${excl}. Tu peux LIRE ces fichiers pour comprendre les interactions, mais tu n'y signales ni n'y corriges rien : ils ont leur propre passage."
}

# Résout les modules ciblés en liste de chemins. Les messages vont sur stderr :
# la fonction est appelée dans `$(...)`, et un avertissement sur stdout
# devenait un « module » de plus.
resolve_modules() {
    local modules_arg="$1"
    local paths=()
    local mod

    if [[ "$modules_arg" == "all" ]]; then
        for mod in "${AVAILABLE_MODULES[@]}"; do
            [[ -d "${PROJECT_ROOT}/${mod}" ]] && paths+=("$mod")
        done
    else
        local -a mod_list=()
        IFS=',' read -ra mod_list <<< "$modules_arg"
        for mod in "${mod_list[@]}"; do
            mod=$(echo "$mod" | xargs)
            mod="${mod%/}"
            if [[ -d "${PROJECT_ROOT}/${mod}" ]]; then
                paths+=("$mod")
            else
                warn "Module introuvable: $mod (ignoré)" >&2
            fi
        done
    fi

    if [[ ${#paths[@]} -eq 0 ]]; then
        err "Aucun module valide trouvé" >&2
        return 1
    fi

    echo "${paths[*]}"
}

# ============================================================================
# Notifications
# ============================================================================
notify_slack() {
    local message="$1"
    if [[ "$NOTIFY_SLACK" != true || -z "$SLACK_WEBHOOK_URL" ]]; then
        return 0
    fi
    # Charge utile construite par jq : un titre d'issue contenant un guillemet
    # cassait le JSON assemblé à la main, et la notification partait en 400.
    local payload
    payload=$(jq -n --arg text "$message" '{text: $text}')
    curl -s -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-type: application/json' \
        -d "$payload" \
        >/dev/null 2>&1 || warn "Échec notification Slack"
}

notify_email() {
    local subject="$1"
    local body="$2"
    if [[ "$NOTIFY_EMAIL" != true || -z "$EMAIL_TO" ]]; then
        return 0
    fi
    echo "$body" | mail -s "$subject" -r "$EMAIL_FROM" "$EMAIL_TO" \
        2>/dev/null || warn "Échec notification email"
}

notify() {
    local status="$1"
    local message="$2"
    local pr_url="${3:-}"

    local icon="[FAIL]"
    [[ "$status" == "success" ]] && icon="[OK]"

    local full_message="AI Pipeline ${icon} - ${message}"
    [[ -n "$pr_url" ]] && full_message="${full_message} - PR: ${pr_url}"

    notify_slack "$full_message"
    notify_email "AI Pipeline - ${status}" "$full_message"

    log "Notification: $full_message"
}
