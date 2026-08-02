#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions git (branches, commits, rollback, vérifications)
# ============================================================================

# Génère le nom de branche
make_branch_name() {
    if [[ -n "$CUSTOM_BRANCH" ]]; then
        echo "$CUSTOM_BRANCH"
        return
    fi

    local date_part
    date_part=$(date +%Y%m%d-%H%M)

    if [[ -n "$ISSUE_NUMBER" ]]; then
        echo "${BRANCH_PREFIX}/issue-${ISSUE_NUMBER}-${date_part}"
    else
        echo "${BRANCH_PREFIX}/${PROFILE}-${date_part}"
    fi
}

# Étiquette des remises créées par le pipeline pour parquer un arbre sale.
WORKTREE_STASH_TAG="ai-pipeline-leftover"

# Parque les modifications suivies non commitées dans une remise étiquetée.
#
# Un `git checkout` ne refuse un arbre sale que si les modifications entrent en
# conflit avec la branche cible : sinon git les EMPORTE silencieusement d'une
# branche à l'autre. Un fichier oublié par l'agent contamine donc toutes les
# branches suivantes, et finit par bloquer le pipeline le jour où le conflit
# apparaît. On remise plutôt que d'écraser : rien n'est perdu, et l'arbre
# repart propre pour la tâche suivante.
#
# Retourne 0 si l'arbre était déjà propre, 1 s'il a fallu remiser.
park_dirty_worktree() {
    local reason="$1"

    # --untracked-files=no : les fichiers non suivis (artefacts de tests, logs
    # rotés) ne voyagent pas d'une branche à l'autre, inutile de les remiser.
    if [[ -z "$(git status --porcelain --untracked-files=no)" ]]; then
        return 0
    fi

    warn "Arbre de travail sale (${reason}) - fichiers non commités :"
    git status --porcelain --untracked-files=no | sed 's/^/      /' | tee -a "$LOG_FILE"

    local label="${WORKTREE_STASH_TAG} | ${reason} | $(date '+%Y-%m-%d %H:%M:%S')"
    if git stash push -m "$label" >> "$LOG_FILE" 2>&1; then
        warn "Modifications remisées - à trier : git stash list | grep '${WORKTREE_STASH_TAG}'"
    else
        err "Échec de la remise - l'arbre reste sale, risque de contamination des branches suivantes"
    fi
    return 1
}

# Retour sur une branche, en parquant les restes si le checkout est refusé.
#
# `git checkout` échoue quand un fichier sale entre en conflit avec la branche
# cible. Traité en `|| true`, cet échec laissait le pipeline coincé sur la
# branche de travail : toutes les tâches suivantes échouaient à leur tour au
# premier checkout et étaient sautées en silence.
return_to_branch() {
    local target="$1"

    if git checkout "$target" >> "$LOG_FILE" 2>&1; then
        return 0
    fi

    warn "Retour sur ${target} refusé (modifications locales) - remisage puis nouvelle tentative"
    park_dirty_worktree "retour sur ${target}" || true

    if git checkout "$target" >> "$LOG_FILE" 2>&1; then
        ok "Retour sur ${target} effectué après remisage"
        return 0
    fi

    err "Impossible de revenir sur ${target} - le pipeline reste sur $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    return 1
}

# Vérifie que l'IA a bien créé des commits, rattrape sinon
check_ai_commits() {
    local base_ref="$1"
    local commit_count
    commit_count=$(git rev-list --count "${base_ref}..HEAD")

    if [[ "$commit_count" -eq 0 ]]; then
        if [[ -n "$(git status --porcelain)" ]]; then
            warn "L'IA a modifié des fichiers sans commit - commit de rattrapage" >&2
            local prefix="bug"
            [[ "$PROFILE" == "security" ]] && prefix="security"
            [[ "$PROFILE" == "quality" ]] && prefix="feat"
            if git add -A >> "$LOG_FILE" 2>&1 && \
                git commit -m "${prefix}: [AI] analyse ${PROFILE} - $(date +%Y-%m-%d)" \
                    >> "$LOG_FILE" 2>&1; then
                commit_count=$(git rev-list --count "${base_ref}..HEAD")
            else
                err "Échec du commit de rattrapage IA" >&2
                echo "0"
                return 1
            fi
        fi
    elif [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        # L'agent a commité, mais a laissé des fichiers modifiés de côté.
        # Ce cas n'était pas détecté : le rattrapage ci-dessus ne se déclenche
        # que sur zéro commit. Résultat, la moitié d'un correctif pouvait
        # disparaître de la PR sans que rien ne le signale (cf. PR #4260, dont
        # le récepteur du garde-fou de sync HA était resté non commité).
        # On ne les commite PAS d'office : rien ne garantit qu'ils relèvent de
        # cette tâche. On les remise et on le dit fort.
        err "L'IA a laissé des modifications NON COMMITÉES malgré ${commit_count} commit(s)" >&2
        err "-> la PR est probablement INCOMPLÈTE, vérifier la remise avant de la relire" >&2
        park_dirty_worktree "restes de $(git rev-parse --abbrev-ref HEAD)" >&2 || true
        notify "failure" "PR potentiellement incomplète : modifications non commitées laissées par l'IA (${ISSUE_NUMBER:+issue #$ISSUE_NUMBER}${PROFILE:+profil $PROFILE}) - voir git stash list" >&2 || true
    fi

    log "Commits créés par l'IA: $commit_count" >&2
    echo "$commit_count"
}

# Vérifie qu'aucun fichier interdit n'a été modifié entre base_ref et HEAD
check_forbidden_files() {
    local base_ref="$1"
    local changed_all
    changed_all=$(git diff --name-only "${base_ref}..HEAD")
    local forbidden_found=false

    while IFS= read -r file; do
        [[ -z "$file" ]] && continue
        for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
            # shellcheck disable=SC2254
            case "$file" in
                $pattern)
                    err "FICHIER INTERDIT modifié: $file (pattern: $pattern)"
                    forbidden_found=true
                    ;;
            esac
        done
    done <<< "$changed_all"

    if [[ "$forbidden_found" == true ]]; then
        return 1
    fi
    return 0
}

# Annulation propre en cas d'erreur
rollback() {
    local branch_name="$1"
    warn "Rollback en cours..."

    cd "$PROJECT_ROOT"

    git checkout -- . 2>/dev/null || true
    git clean -fd 2>/dev/null || true
    git checkout "$BASE_BRANCH" 2>/dev/null || true
    git branch -D "$branch_name" 2>/dev/null || true

    warn "Rollback terminé - retour sur $BASE_BRANCH"
}

# Nettoyage des branches ai/* mergées
cleanup_branches() {
    header "Nettoyage des branches ai/* mergées"
    cd "$PROJECT_ROOT"

    local merged
    merged=$(git branch --merged "$BASE_BRANCH" | grep "  ${BRANCH_PREFIX}/" || true)

    if [[ -z "$merged" ]]; then
        ok "Aucune branche ai/* mergée à nettoyer"
        return 0
    fi

    echo "$merged" | while read -r branch; do
        branch=$(echo "$branch" | xargs)
        log "Suppression locale: $branch"
        git branch -d "$branch" 2>/dev/null || true

        if git ls-remote --heads "$REPO_REMOTE" "$branch" | grep -q .; then
            log "Suppression remote: $branch"
            git push "$REPO_REMOTE" --delete "$branch" 2>/dev/null || true
        fi
    done

    ok "Nettoyage terminé"
}
