#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions communes (logging, notifications, prérequis)
# ============================================================================

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="${LOGS_DIR}/run-${TIMESTAMP}.log"

log()    { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
ok()     { echo -e "${GREEN}[OK]${NC} $*" | tee -a "$LOG_FILE"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*" | tee -a "$LOG_FILE"; }
err()    { echo -e "${RED}[ERR]${NC} $*" | tee -a "$LOG_FILE"; }
header() { echo -e "\n${CYAN}══════════════════════════════════════════${NC}" | tee -a "$LOG_FILE"
           echo -e "${CYAN}  $*${NC}" | tee -a "$LOG_FILE"
           echo -e "${CYAN}══════════════════════════════════════════${NC}\n" | tee -a "$LOG_FILE"; }

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
            exit 1
            ;;
    esac
}

check_ai_cli() {
    check_ai_agent_config
    case "$AI_AGENT" in
        claude)
            command -v "$CLAUDE_CMD" >/dev/null || {
                err "Prérequis manquant: $CLAUDE_CMD (Claude Code CLI)"
                exit 1
            }
            ;;
        codex)
            command -v "$CODEX_CMD" >/dev/null || {
                err "Prérequis manquant: $CODEX_CMD (Codex CLI)"
                exit 1
            }
            ;;
    esac
}

# Détecte une sortie d'agent IA causée par un rate limit / quota épuisé.
# Renvoie 0 si la sortie ressemble à un rate limit, non-zéro sinon.
_ai_output_is_rate_limit() {
    local output_file="$1"
    [[ -s "$output_file" ]] || return 1
    # "You've hit your limit · resets ..." (Claude Code), "rate limit", "quota",
    # "usage limit", "429", "credits exhausted/insufficient" (Codex/OpenAI), etc.
    grep -qiE "hit your (usage )?limit|usage limit reached|rate[ _-]?limit|quota|too many requests|\b429\b|credits? (exhausted|insufficient|exceeded)|insufficient_quota|resets (at )?[0-9]" "$output_file"
}

# Sleep interruptible par signal (Ctrl+C / SIGTERM via le trap d'orchestrator.sh).
# On découpe en tranches de 30s pour que le trap ait un signal frais à traiter
# et qu'on puisse loguer une progression utile pendant l'attente.
_ai_sleep_interruptible() {
    local total="$1"
    local elapsed=0
    local chunk=30
    while (( elapsed < total )); do
        local remaining=$(( total - elapsed ))
        (( remaining < chunk )) && chunk=$remaining
        sleep "$chunk" || return $?
        elapsed=$(( elapsed + chunk ))
    done
    return 0
}

# Exécute une seule fois la CLI de l'agent IA. Pas de retry ici.
_run_ai_agent_once() {
    local mode="$1" prompt="$2" output_file="$3"
    local timeout_s
    timeout_s=$(ai_agent_timeout)

    case "$AI_AGENT" in
        claude)
            local -a claude_args=("$CLAUDE_CMD" -p "$prompt")
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
                --cd "$PROJECT_ROOT"
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

        if [[ $exit_code -eq 0 ]]; then
            return 0
        fi

        # Ne pas retry sur un timeout (124) — c'est un vrai problème de durée,
        # pas un rate limit.
        if [[ $exit_code -eq 124 ]]; then
            return $exit_code
        fi

        if ! _ai_output_is_rate_limit "$output_file"; then
            # Vrai échec (auth, crash, etc.) → on remonte l'erreur immédiatement.
            return $exit_code
        fi

        if (( attempt >= max_retries )); then
            err "${label}: rate limit toujours présent après ${attempt} retry(s), abandon"
            return $exit_code
        fi

        attempt=$(( attempt + 1 ))
        local hint
        hint=$(grep -oiE "resets [0-9][0-9aApPmM:\. -]+(\([^)]+\))?" "$output_file" | head -1 || true)
        warn "${label}: rate limit détecté${hint:+ ($hint)} — attente ${delay}s avant retry ${attempt}/${max_retries}"
        notify_slack "AI Pipeline [WAIT] - ${label} rate-limited, retry ${attempt}/${max_retries} dans ${delay}s${hint:+ — $hint}"

        if ! _ai_sleep_interruptible "$delay"; then
            err "Attente interrompue, abandon des retries"
            return $exit_code
        fi
        log "Reprise après attente rate-limit (tentative ${attempt}/${max_retries})"
    done
}

check_ai_tokens() {
    check_ai_cli

    local label
    label=$(ai_agent_label)
    local test_output
    local test_exit=0
    test_output=$(mktemp)

    run_ai_agent "read" "Réponds uniquement OK" "$test_output" || test_exit=$?

    if [[ $test_exit -ne 0 ]]; then
        if grep -qi "rate\|limit\|exceeded\|quota\|429\|capacity\|credits" "$test_output"; then
            rm -f "$test_output"
            err "Limite de tokens/crédits ${label} atteinte"
            return 1
        fi
        warn "${label} a échoué au test de disponibilité (exit $test_exit), tentative quand même"
        tail -5 "$test_output" 2>/dev/null || true
        rm -f "$test_output"
        return 0
    fi

    rm -f "$test_output"
    ok "Agent IA disponible: ${label}"
    return 0
}

# ============================================================================
# Contexte projet injecté dans TOUS les prompts IA
# ============================================================================
# Sans ce bloc, chaque audit redécouvre le projet de zéro et re-signale les
# mêmes décisions d'architecture délibérées comme si c'étaient des bugs. Elles
# sont toutes documentées et justifiées dans CLAUDE.md — l'agent doit l'avoir lu
# avant d'ouvrir la moindre issue.
ai_project_context() {
    cat <<'CONTEXT'
## Le projet

Moteur VTuber : un avatar 3D animé par une IA conversationnelle, avec émotions
temps réel (espace PAD), mémoire à long terme, conscience autonome, cycle de
sommeil, pulsions intrinsèques et projets de travail.

- `backend/` — Django + Channels servi par Uvicorn. Apps : `ai` (routage
  multi-provider), `communication` (WebSocket, Telegram), `pipeline`
  (perception → routeur → processeur), `memory`, `emotion`, `drives`,
  `conscience`, `identity`, `projects`, `modules` (système de plugins, dont la
  Forge où l'IA écrit ses propres modules à l'exécution), `GestionSysteme`
  (admin rendu côté serveur), `configs` (registre de configuration).
- `frontend/` — Vite + TypeScript + Three.js + VRM. Rendu 3D, retarget
  d'animations Mixamo, TTS navigateur, lip-sync.
- Base SQLite en WAL, sous écriture concurrente permanente (six boucles de fond).
- Langue du produit : français. Code et commentaires en français.

**Lis `CLAUDE.md` à la racine AVANT toute analyse.** Il documente l'architecture
et, surtout, le POURQUOI de choix qui ont l'air d'erreurs vus de loin.

## Choix DÉLIBÉRÉS — ne les signale jamais comme des défauts

Chacun est documenté dans CLAUDE.md avec sa justification. Les re-signaler fait
perdre un cycle complet à chaque passage :

- **Exceptions avalées en masse** (`logger.debug`, `except: pass`, replis
  silencieux). Une boucle de fond n'a pas de superviseur : une exception qui
  s'échappe la tue pour la durée du processus. Elles sont comptées par
  `utils/degradation.py`, c'est le compromis assumé.
- **Le tampon court-terme de la mémoire n'est pas filtré par `person_id`.** Ce
  n'est pas une fuite : c'est la prémisse du moteur (« quelqu'un dans une pièce
  entend ce qui s'y dit »). L'arbitrage est confié au prompt, pas à un `WHERE`.
- **`DASHBOARD_REQUIRE_AUTH=False` par défaut**, compensé par une écoute sur
  loopback : une installation neuve n'a pas encore de superuser.
- **Le sandbox de la Forge s'exécute in-process.** Le modèle de menace est la
  prévention d'accident et l'injection de prompt, pas l'isolation OS.
- **SQLite en WAL avec `synchronous=NORMAL`**, et le PRAGMA est invisible en
  test (base en mémoire) : c'est l'`init_command` déclaré qui est testé.
- **Les pieds de bloc du prompt système sont volontairement inconsistants**
  (`--- FIN PROJET ---`, `--- FIN ---`) : les unifier change ce que le modèle lit.
- **`emotion_policy` par défaut à OFF sur les projets**, **les émotions sont
  stockées en anglais et affichées en français**, **une seule horloge naïve
  locale** (`date.today()`, jamais `timezone.localdate()`).

Si tu crois vraiment tenir un problème sur l'un de ces points, il te faut un
scénario de défaillance concret et reproductible — sinon, passe.
CONTEXT
}

# ============================================================================
# Politique de tests injectée dans TOUS les prompts IA
# ============================================================================
# Aucun workflow GitHub Actions n'existe sur ce dépôt : rien ne validera la PR
# après coup. Mais la suite complète (~1000 tests pytest + tsc) est trop longue
# et trop coûteuse pour tourner à chaque tâche. D'où le compromis : vérification
# CIBLÉE obligatoire sur ce qu'on a touché, suite complète interdite.
#   ai_test_policy write  → modes fix / worker (l'agent peut modifier le code)
#   ai_test_policy read   → mode audit (lecture seule)
ai_test_policy() {
    local mode="${1:-write}"

    if [[ "$mode" == "read" ]]; then
        cat <<'POLICY'
## Politique de TESTS (règle ABSOLUE)

- N'exécute AUCUN test : ni `pytest`, ni `manage.py test`, ni `npm test`, ni script de reproduction.
- Ne signale JAMAIS "tests manquants", "couverture insuffisante" ou "il faudrait un test de non-régression" : c'est hors périmètre de cet audit et ce type d'issue est systématiquement rejeté.
- La correction suggérée dans une issue doit porter sur le CODE, jamais sur l'ajout de tests.
POLICY
        return 0
    fi

    cat <<'POLICY'
## Politique de TESTS (règle ABSOLUE - coût et durée)

Aucun CI ne relira ton travail : la vérification, c'est toi, puis un humain.
Mais la suite complète est hors de question (≈1000 tests pytest, plusieurs
minutes de `tsc`). Tu vérifies donc CIBLÉ, et seulement ce que tu as touché.

- N'exécute JAMAIS la suite complète : ni `pytest` nu, ni `pytest backend/tests/`, ni `python manage.py test`, ni `npm test`, ni `tox`.
- N'écris AUCUN nouveau fichier ni fonction de test, même "pour valider" ta correction. Aucune PR de ce pipeline n'a pour objet d'ajouter de la couverture.
- Ne crée PAS de script jetable de reproduction : relis le code à la place.
- Ne modifie un test existant QUE si ta correction le casse mécaniquement (signature ou API changée). Dans ce cas : adaptation minimale, jamais de réécriture.
- Vérification autorisée, et une seule fois, à la fin :
  - Python : `python -m py_compile <fichiers modifiés>`, puis AU PLUS UN fichier de test ciblé s'il en existe un qui couvre la zone touchée, par exemple `python -m pytest backend/tests/test_pipeline_signals.py -x -q`.
  - TypeScript : `cd frontend && npx tsc --noEmit` — c'est le garde-fou dur du frontend, ne le saute pas si tu as modifié `frontend/src/`.
- Si un test ciblé échoue à cause de ta modification, corrige ta modification. S'il échouait déjà avant, ne le touche pas et signale-le dans le corps de la PR.

Exception unique : si l'issue traitée demande EXPLICITEMENT d'ajouter ou de corriger un test, fais uniquement ce qui est demandé.
POLICY
}

# Vérifie les prérequis système
check_prerequisites() {
    local missing=()

    command -v git    >/dev/null || missing+=("git")
    command -v gh     >/dev/null || missing+=("gh (GitHub CLI)")
    check_ai_cli

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Prérequis manquants: ${missing[*]}"
        exit 1
    fi

    if ! gh auth status &>/dev/null; then
        err "GitHub CLI non authentifié. Lancer: gh auth login"
        exit 1
    fi

    cd "$PROJECT_ROOT"
    # Vérifier que le repo est propre (en ignorant les fichiers du pipeline)
    local dirty
    dirty=$(git status --porcelain | grep -v "scripts/ai_pipeline/" || true)
    if [[ -n "$dirty" ]]; then
        err "Le repo a des changements non commités. Commit ou stash d'abord."
        echo "$dirty"
        exit 1
    fi

    ok "Prérequis validés"
}

# Vérifie les prérequis légers (pas besoin de repo propre)
check_prerequisites_light() {
    local missing=()
    command -v gh     >/dev/null || missing+=("gh (GitHub CLI)")
    check_ai_cli
    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Prérequis manquants: ${missing[*]}"
        exit 1
    fi
    if ! gh auth status &>/dev/null; then
        err "GitHub CLI non authentifié. Lancer: gh auth login"
        exit 1
    fi
    ok "Prérequis validés"
}

# Résout les modules ciblés en liste de chemins
resolve_modules() {
    local modules_arg="$1"
    local paths=()

    if [[ "$modules_arg" == "all" ]]; then
        for mod in "${AVAILABLE_MODULES[@]}"; do
            if [[ -d "${PROJECT_ROOT}/${mod}" ]]; then
                paths+=("$mod")
            fi
        done
    else
        IFS=',' read -ra mod_list <<< "$modules_arg"
        for mod in "${mod_list[@]}"; do
            mod=$(echo "$mod" | xargs)
            if [[ -d "${PROJECT_ROOT}/${mod}" ]]; then
                paths+=("$mod")
            else
                warn "Module introuvable: $mod (ignoré)"
            fi
        done
    fi

    if [[ ${#paths[@]} -eq 0 ]]; then
        err "Aucun module valide trouvé"
        exit 1
    fi

    echo "${paths[*]}"
}

# Lance les tests
run_tests() {
    if [[ "$SKIP_TESTS" == true || "$RUN_TESTS" != true ]]; then
        warn "Tests ignorés (--no-tests ou config)"
        return 0
    fi

    header "Lancement des tests"
    cd "$PROJECT_ROOT"

    local test_output
    local test_exit=0

    test_output=$(timeout "$TEST_TIMEOUT" $TEST_CMD $TEST_ARGS 2>&1) || test_exit=$?

    echo "$test_output" >> "$LOG_FILE"

    if [[ $test_exit -ne 0 ]]; then
        err "Tests échoués (exit code: $test_exit)"
        echo "$test_output" | tail -20
        return 1
    fi

    ok "Tests passés"
    return 0
}

# Notification Slack
notify_slack() {
    local message="$1"
    if [[ "$NOTIFY_SLACK" != true || -z "$SLACK_WEBHOOK_URL" ]]; then
        return 0
    fi
    curl -s -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-type: application/json' \
        -d "{\"text\": \"${message}\"}" \
        >/dev/null 2>&1 || warn "Échec notification Slack"
}

# Notification email
notify_email() {
    local subject="$1"
    local body="$2"
    if [[ "$NOTIFY_EMAIL" != true || -z "$EMAIL_TO" ]]; then
        return 0
    fi
    echo "$body" | mail -s "$subject" -r "$EMAIL_FROM" "$EMAIL_TO" \
        2>/dev/null || warn "Échec notification email"
}

# Notification générique
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

    log "Notification envoyée: $full_message"
}
