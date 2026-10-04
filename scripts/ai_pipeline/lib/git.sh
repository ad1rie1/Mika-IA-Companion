#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions git (worktree, branches, commits, vérifications)
# ============================================================================
#
# Tout ce qui suit agit dans WORK_ROOT, le worktree du pipeline, jamais dans la
# copie de travail de PROJECT_ROOT. Les branches de tâche partent de BASE_REF
# (l'état distant de la branche de base) en tête détachée : `main` est extrait
# dans la copie de l'utilisateur, et git refuse d'extraire une même branche
# dans deux worktrees.

# Génère le nom de branche. À la seconde : deux tâches sur une même issue dans
# la même minute (issue relabellisée aussitôt, re-lancement manuel) donnaient
# le même nom, et le second push était refusé.
make_branch_name() {
    if [[ -n "$CUSTOM_BRANCH" ]]; then
        echo "$CUSTOM_BRANCH"
        return
    fi

    local date_part
    date_part=$(date +%Y%m%d-%H%M%S)

    if [[ -n "$ISSUE_NUMBER" ]]; then
        echo "${BRANCH_PREFIX}/issue-${ISSUE_NUMBER}-${date_part}"
    else
        echo "${BRANCH_PREFIX}/${PROFILE}-${date_part}"
    fi
}

# -- Verrou -------------------------------------------------------------------
# Deux pipelines dans le même worktree (run.sh + une tâche cron, ou deux
# webhooks rapprochés) se remettaient à zéro l'un l'autre en pleine tâche. Le
# verrou est tenu pour toute la durée de l'orchestrateur ; ses processus fils
# (l'agent) en héritent, si bien qu'un agent orphelin qui travaille encore
# dans le worktree le garde aussi.
acquire_pipeline_lock() {
    local common_dir lock
    common_dir=$(git -C "$PROJECT_ROOT" rev-parse --path-format=absolute --git-common-dir)
    lock="${common_dir}/ai-pipeline.lock"
    exec {PIPELINE_LOCK_FD}>"$lock"
    if ! flock -n "$PIPELINE_LOCK_FD"; then
        warn "Une autre instance du pipeline travaille déjà (verrou ${lock}) - abandon"
        exit "$EXIT_BUSY"
    fi
}

# -- Worktree -----------------------------------------------------------------

# Exclusions locales (.git/info/exclude, partagé par tous les worktrees) : le
# worktree lui-même pour la copie principale, et les liens vers les dépendances
# pour le worktree — `node_modules/` dans .gitignore ne matche qu'un dossier,
# pas un lien symbolique, que `git status` aurait montré comme fichier à
# commiter.
_ensure_local_excludes() {
    local exclude rel
    exclude="$(git -C "$PROJECT_ROOT" rev-parse --path-format=absolute --git-common-dir)/info/exclude"
    mkdir -p "$(dirname "$exclude")"
    touch "$exclude"

    local -a wanted=()
    case "$WORK_ROOT" in
        "$PROJECT_ROOT"/*) wanted+=("/${WORK_ROOT#"$PROJECT_ROOT"/}/") ;;
    esac
    for rel in "${WORKSPACE_SHARED_PATHS[@]}"; do
        wanted+=("/${rel}")
    done

    local line
    for line in "${wanted[@]}"; do
        grep -qxF -- "$line" "$exclude" || printf '%s\n' "$line" >> "$exclude"
    done
}

# Liens vers les dépendances non suivies de la copie principale.
_link_shared_paths() {
    local rel src dst
    for rel in "${WORKSPACE_SHARED_PATHS[@]}"; do
        src="${PROJECT_ROOT}/${rel}"
        dst="${WORK_ROOT}/${rel}"
        [[ -e "$src" ]] || continue
        [[ -L "$dst" || -e "$dst" ]] && continue
        mkdir -p "$(dirname "$dst")"
        ln -s "$src" "$dst"
    done
}

# Crée le worktree au besoin, le remet à zéro et s'y place.
ensure_workspace() {
    _ensure_local_excludes

    if ! git -C "$PROJECT_ROOT" fetch --quiet "$REPO_REMOTE" "$BASE_BRANCH" >> "$LOG_FILE" 2>&1; then
        err "git fetch ${REPO_REMOTE} ${BASE_BRANCH} a échoué"
        return 1
    fi

    if [[ ! -e "${WORK_ROOT}/.git" ]]; then
        if [[ -e "$WORK_ROOT" ]] && [[ -n "$(ls -A "$WORK_ROOT" 2>/dev/null)" ]]; then
            err "${WORK_ROOT} existe et n'est pas un worktree git - à vérifier à la main"
            return 1
        fi
        # Un worktree supprimé à la main laisse une entrée orpheline qui fait
        # refuser le `worktree add` au même chemin.
        git -C "$PROJECT_ROOT" worktree prune >> "$LOG_FILE" 2>&1 || true
        log "Création du worktree du pipeline : ${WORK_ROOT}"
        mkdir -p "$(dirname "$WORK_ROOT")"
        if ! git -C "$PROJECT_ROOT" worktree add --detach "$WORK_ROOT" "$BASE_REF" >> "$LOG_FILE" 2>&1; then
            err "git worktree add a échoué (voir $LOG_FILE)"
            return 1
        fi
    fi

    # Un dossier qui contient un `.git` n'est pas forcément NOTRE worktree : on
    # ne remet à zéro que si son dépôt est bien celui de PROJECT_ROOT.
    local ours theirs
    ours=$(git -C "$PROJECT_ROOT" rev-parse --path-format=absolute --git-common-dir)
    theirs=$(git -C "$WORK_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "")
    if [[ "$ours" != "$theirs" ]]; then
        err "${WORK_ROOT} appartient à un autre dépôt (${theirs:-aucun}) - refus d'y travailler"
        return 1
    fi

    cd "$WORK_ROOT" || return 1
    workspace_reset "début de tâche" || return 1
    _link_shared_paths
}

# Sauvegarde ce qui traîne dans le worktree (modifications et fichiers non
# suivis) en patch dans les journaux, pour ne rien perdre de ce qu'un agent a
# laissé. Retourne 0 si l'arbre était propre, 1 s'il a fallu sauvegarder.
#
# Une remise (stash) aurait aussi gardé ces restes, mais la pile de remises est
# commune à tous les worktrees : elle atterrissait dans le `git stash list` de
# l'utilisateur, à portée d'un `git stash pop`.
save_leftovers() {
    local reason="$1"
    [[ -z "$(git status --porcelain)" ]] && return 0

    warn "Worktree sale (${reason}) - fichiers laissés :"
    git status --porcelain | sed 's/^/      /' | tee -a "$LOG_FILE"

    local patch="${LOGS_DIR}/leftover-$(date +%Y%m%d-%H%M%S)-$$.patch"
    # L'index du worktree est le sien : y ajouter ce qui traîne ne touche pas
    # celui de l'utilisateur.
    if git add -A >> "$LOG_FILE" 2>&1 \
        && git diff --cached --binary HEAD > "$patch" 2>> "$LOG_FILE"; then
        warn "Restes sauvegardés : ${patch} (git apply pour les récupérer)"
    else
        err "Sauvegarde des restes impossible - ils seront perdus à la remise à zéro"
    fi
    git reset -q >> "$LOG_FILE" 2>&1 || true
    return 1
}

# Remet le worktree à l'état de BASE_REF, tête détachée. N'agit QUE dans le
# worktree du pipeline : c'est la seule fonction autorisée à `reset --hard` et
# à `clean`, et elle refuse de le faire ailleurs.
workspace_reset() {
    local reason="${1:-remise à zéro}"

    if [[ "$(pwd -P)" != "$(cd "$WORK_ROOT" && pwd -P)" ]]; then
        err "workspace_reset appelé hors du worktree du pipeline ($(pwd)) - refusé"
        return 1
    fi

    # Une opération laissée en plan par un agent interrompu bloque tout checkout.
    git rebase --abort >/dev/null 2>&1 || true
    git merge --abort >/dev/null 2>&1 || true
    git cherry-pick --abort >/dev/null 2>&1 || true

    save_leftovers "$reason" || true

    if ! git checkout -q -f --detach "$BASE_REF" >> "$LOG_FILE" 2>&1; then
        err "Impossible de revenir sur ${BASE_REF} dans le worktree"
        return 1
    fi
    git reset -q --hard "$BASE_REF" >> "$LOG_FILE" 2>&1
    git clean -q -fd >> "$LOG_FILE" 2>&1
}

# Ouvre une branche de tâche sur l'état distant à jour de la branche de base.
start_task_branch() {
    local branch_name="$1"
    git fetch --quiet "$REPO_REMOTE" "$BASE_BRANCH" >> "$LOG_FILE" 2>&1 || {
        err "git fetch ${REPO_REMOTE} ${BASE_BRANCH} a échoué"
        return 1
    }
    workspace_reset "avant ${branch_name}" || return 1
    git checkout -q -B "$branch_name" "$BASE_REF" >> "$LOG_FILE" 2>&1 || {
        err "git checkout -B ${branch_name} a échoué"
        return 1
    }
}

# Referme une branche de tâche : retour sur BASE_REF, puis suppression de la
# branche locale — sauf si elle porte des commits qui n'existent nulle part
# ailleurs (tâche interrompue, --no-create) : on ne jette pas un travail fini.
#   finish_task_branch <branche> [keep]
finish_task_branch() {
    local branch_name="$1" keep="${2:-}"
    workspace_reset "fin de ${branch_name}" || return 1

    git show-ref --verify --quiet "refs/heads/${branch_name}" || return 0
    if [[ "$keep" == "keep" ]]; then
        log "Branche locale conservée : ${branch_name}"
        return 0
    fi

    local unpushed
    unpushed=$(git rev-list --count "$branch_name" --not "$BASE_REF" --remotes 2>/dev/null || echo 0)
    if [[ "$unpushed" -gt 0 ]]; then
        warn "Branche ${branch_name} conservée : ${unpushed} commit(s) poussé(s) nulle part"
        return 0
    fi
    git branch -q -D "$branch_name" >> "$LOG_FILE" 2>&1 || true
}

# Abandon d'une tâche : la branche part, même avec ses commits (échec de
# l'agent, fichier protégé touché).
rollback() {
    local branch_name="$1"
    warn "Rollback de ${branch_name}..."
    workspace_reset "rollback de ${branch_name}" || return 1
    git branch -q -D "$branch_name" >> "$LOG_FILE" 2>&1 || true
    warn "Rollback terminé - worktree revenu sur ${BASE_REF}"
}

# Vérifie que l'IA a bien créé des commits, rattrape sinon.
# Écrit le nombre de commits sur stdout, tout le reste sur stderr.
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
            # `add -A` est sûr ici : le worktree est celui du pipeline, et les
            # dépendances liées sont exclues.
            if git add -A >> "$LOG_FILE" 2>&1 && \
                git commit -q -m "${prefix}: [AI] analyse ${PROFILE:-issue} - $(date +%Y-%m-%d)" \
                    >> "$LOG_FILE" 2>&1; then
                commit_count=$(git rev-list --count "${base_ref}..HEAD")
            else
                err "Échec du commit de rattrapage IA" >&2
                echo "0"
                return 1
            fi
        fi
    elif [[ -n "$(git status --porcelain)" ]]; then
        # L'agent a commité, mais a laissé des fichiers modifiés de côté : la
        # moitié d'un correctif pouvait disparaître de la PR sans que rien ne le
        # signale. On ne les commite PAS d'office (rien ne garantit qu'ils
        # relèvent de cette tâche) : la remise à zéro de fin de tâche les
        # sauvegardera en patch, et on le dit fort.
        err "L'IA a laissé des modifications NON COMMITÉES malgré ${commit_count} commit(s)" >&2
        git status --porcelain | sed 's/^/      /' >&2
        err "-> la PR est probablement INCOMPLÈTE : les restes seront sauvegardés dans ${LOGS_DIR}/leftover-*.patch" >&2
        notify "failure" "PR potentiellement incomplète : modifications non commitées laissées par l'IA (${ISSUE_NUMBER:+issue #$ISSUE_NUMBER}${PROFILE:+profil $PROFILE}) - voir ${LOGS_DIR}/leftover-*.patch" >&2 || true
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
    local file pattern

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

    [[ "$forbidden_found" != true ]]
}

# Nettoyage des branches ai/* déjà intégrées à la branche de base distante
cleanup_branches() {
    header "Nettoyage des branches ${BRANCH_PREFIX}/* mergées"
    git -C "$PROJECT_ROOT" fetch --quiet --prune "$REPO_REMOTE" >> "$LOG_FILE" 2>&1 || true

    local -a merged=()
    mapfile -t merged < <(git -C "$PROJECT_ROOT" for-each-ref --format='%(refname:short)' \
        --merged "$BASE_REF" "refs/heads/${BRANCH_PREFIX}")

    if [[ ${#merged[@]} -eq 0 ]]; then
        ok "Aucune branche ${BRANCH_PREFIX}/* mergée à nettoyer"
        return 0
    fi

    local branch
    for branch in "${merged[@]}"; do
        log "Suppression locale: $branch"
        git -C "$PROJECT_ROOT" branch -d "$branch" >> "$LOG_FILE" 2>&1 || true

        if git -C "$PROJECT_ROOT" ls-remote --exit-code --heads "$REPO_REMOTE" "$branch" >/dev/null 2>&1; then
            log "Suppression remote: $branch"
            git -C "$PROJECT_ROOT" push "$REPO_REMOTE" --delete "$branch" >> "$LOG_FILE" 2>&1 || true
        fi
    done

    ok "Nettoyage terminé"
}
