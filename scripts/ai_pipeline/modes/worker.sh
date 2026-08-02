#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode WORKER (traite les issues taggées Propose_AI_PR)
# ============================================================================

# Traite une seule issue. Retourne 0 si l'issue est prise en charge (avec ou
# sans modifications ou erreur "attendue" comme un timeout IA), non-zéro si
# une commande critique du pipeline (git, gh) échoue de façon inattendue.
#
# Les `return 0` dans le corps = "skip cette issue proprement, passer à la
# suivante". `set -e` (hérité) fait échouer la fonction sur toute commande
# non attrapée ; la boucle appelante attrape ces échecs via `|| { ... }`
# pour ne pas interrompre le traitement des issues restantes.
_worker_process_issue() {
    local issue_number="$1"
    local issue_title="$2"
    local issue_labels="$3"
    local worker_profile="$4"

    header "Traitement issue #${issue_number}: ${issue_title}"

    # Déterminer le type depuis les labels (pour le préfixe de commit)
    local profile="bugs"
    if [[ "$issue_labels" == *"ai-security"* || "$issue_labels" == *"security"* ]]; then
        profile="security"
    elif [[ "$issue_labels" == *"ai-quality"* || "$issue_labels" == *"quality"* ]]; then
        profile="quality"
    fi
    log "Type déduit: $profile"
    PROFILE="$profile"

    # Vérifier s'il y a déjà une PR liée à cette issue
    local existing_pr
    existing_pr=$(gh pr list --state open --limit 1000 --search "issue #${issue_number} in:title" \
        --json number,headRefName,url \
        --template '{{range .}}{{.number}}|{{.headRefName}}|{{.url}}{{"\n"}}{{end}}' \
        2>/dev/null || echo "")

    # S'il y a déjà une PR, la fermer et supprimer sa branche
    if [[ -n "$existing_pr" ]]; then
        while IFS='|' read -r pr_num pr_branch pr_url; do
            [[ -z "$pr_num" ]] && continue
            warn "PR existante #${pr_num} trouvée, fermeture pour re-création..."
            gh pr close "$pr_num" --comment "Fermée automatiquement par AI Pipeline (re-création demandée via Propose_AI_PR)" \
                2>&1 | tee -a "$LOG_FILE" || true
            git push "$REPO_REMOTE" --delete "$pr_branch" 2>/dev/null || true
            git branch -D "$pr_branch" 2>/dev/null || true
            ok "PR #${pr_num} fermée et branche $pr_branch supprimée"
        done <<< "$existing_pr"
    fi

    # Récupérer le contenu complet de l'issue (titre + body + commentaires)
    local issue_full
    issue_full=$(gh issue view "$issue_number" \
        --json title,body,comments \
        --template '## Issue #{{.number}}: {{.title}}

{{.body}}

{{if .comments}}## Commentaires des reviewers
{{range .comments}}
---
{{.body}}
{{end}}{{end}}' 2>/dev/null || echo "Impossible de charger l'issue #${issue_number}")

    # Créer la branche
    ISSUE_NUMBER="$issue_number"
    local branch_name="${BRANCH_PREFIX}/issue-${issue_number}-$(date +%Y%m%d-%H%M)"
    log "Branche: $branch_name"

    if [[ "$DRY_RUN" == true ]]; then
        log "Dry-run: issue #${issue_number} serait traitée"
        return 0
    fi

    local original_branch
    original_branch=$(git rev-parse --abbrev-ref HEAD)

    # Repartir d'un arbre propre : un reste non commité d'une tâche précédente
    # est emporté par le checkout et se retrouve dans la branche suivante, puis
    # fait échouer tous les checkouts dès qu'il entre en conflit.
    park_dirty_worktree "avant traitement de l'issue #${issue_number}" || true

    # Préparer la branche de travail — tout échec git = sortie non-zéro
    # attrapée par la boucle appelante (on ne bloque pas les issues suivantes).
    git checkout "$BASE_BRANCH" 2>&1 | tee -a "$LOG_FILE" || {
        err "git checkout $BASE_BRANCH a échoué pour l'issue #${issue_number}"
        return 1
    }
    git pull "$REPO_REMOTE" "$BASE_BRANCH" 2>&1 | tee -a "$LOG_FILE" || {
        err "git pull a échoué pour l'issue #${issue_number}"
        return 1
    }
    git checkout -b "$branch_name" 2>&1 | tee -a "$LOG_FILE" || {
        err "git checkout -b $branch_name a échoué pour l'issue #${issue_number}"
        return 1
    }

    local base_ref
    base_ref=$(git rev-parse HEAD)

    # Construire le prompt
    local prompt
    prompt=$(cat <<PROMPT
${worker_profile}

$(ai_project_context)

## Contexte : Issue GitHub à corriger

${issue_full}

## Périmètre

Tu travailles sur l'ensemble du projet. Lis le fichier CLAUDE.md à la racine pour comprendre l'architecture.
Corrige le problème décrit dans l'issue ci-dessus. Prends en compte les commentaires des reviewers s'il y en a.

## Contraintes ABSOLUES

1. Tu peux LIRE, MODIFIER des fichiers et exécuter des commandes bash
2. Pour chaque correction, fais un commit séparé avec : git add <fichiers> && git commit -m "prefix: description"
   - Préfixes obligatoires : bug: / security: / feat: selon le type de correction
   - Message de commit en français
3. Tu ne dois JAMAIS exécuter : git push, git branch, git checkout, git merge, git rebase, git reset, git stash
4. Tu ne dois JAMAIS exécuter de commandes système dangereuses (rm -rf, etc.)
5. Tu ne dois JAMAIS modifier les fichiers protégés : settings.py, manage.py, */migrations/*, *.env, personality.yaml, data/*, uploads/*, pytest.ini, requirements.txt, package.json
6. Tu ne dois JAMAIS ajouter d'alias ou renommer des fonctions existantes
7. Chaque modification doit être minimale et ciblée
8. Lis TOUJOURS le fichier CLAUDE.md à la racine du projet et respecte ses règles
9. Respecte la politique de tests ci-dessous : pas de nouveaux tests, pas de suite complète, vérification ciblée uniquement

$(ai_test_policy write)
PROMPT
)

    # Lancer l'agent IA (background + wait pour que Ctrl+C soit interceptable)
    log "Lancement IA pour issue #${issue_number} (${profile})..."
    local start_time
    start_time=$(date +%s)
    local ai_exit=0
    local ai_out
    ai_out=$(mktemp)
    run_ai_agent "write" "$prompt" "$ai_out" &
    local ai_pid=$!
    wait "$ai_pid" || ai_exit=$?
    local ai_output
    ai_output=$(cat "$ai_out")
    rm -f "$ai_out"

    local elapsed=$(( $(date +%s) - start_time ))
    echo "$ai_output" >> "$LOG_FILE"

    if [[ $ai_exit -ne 0 ]]; then
        local reason="erreur inconnue"
        [[ $ai_exit -eq 124 ]] && reason="timeout après ${elapsed}s (max $(ai_agent_timeout)s)"
        err "$(ai_agent_label) a échoué sur issue #${issue_number} (exit: $ai_exit - ${reason})"
        rollback "$branch_name" || true
        return_to_branch "$original_branch" || true
        return 0
    fi

    ok "IA terminée pour issue #${issue_number} en ${elapsed}s"

    # Vérifier les commits
    local commit_count
    if ! commit_count=$(check_ai_commits "$base_ref"); then
        err "Impossible de finaliser les commits IA pour l'issue #${issue_number}"
        rollback "$branch_name" || true
        return_to_branch "$original_branch" || true
        return 0
    fi

    if [[ "$commit_count" -eq 0 ]]; then
        warn "Aucune modification pour l'issue #${issue_number}"
        local no_change_comment
        no_change_comment=$(cat <<NOCHANGE
## Worker AI Pipeline — aucune modification produite

Le worker a analysé cette issue mais n'a généré **aucun commit**. Causes possibles :
- L'agent IA a estimé que le code actuel ne nécessitait pas de correction
- L'issue manque de précision sur la correction attendue
- Le problème décrit est en dehors du périmètre du worker

**Action** : précise l'issue (fichier, ligne, comportement attendu) puis remets le label \`Propose_AI_PR\` pour relancer.

> Tag \`Propose_AI_PR\` retiré pour éviter les ré-exécutions en boucle.
NOCHANGE
)
        gh issue comment "$issue_number" --body "$no_change_comment" 2>&1 | tee -a "$LOG_FILE" || true
        gh issue edit "$issue_number" \
            --remove-label "Propose_AI_PR" \
            --add-label "ai-failed-no-changes" \
            2>&1 | tee -a "$LOG_FILE" || warn "Échec swap labels pour issue #${issue_number}"
        return_to_branch "$original_branch" || true
        git branch -D "$branch_name" 2>/dev/null || true
        return 0
    fi

    # Vérifier fichiers interdits
    if ! check_forbidden_files "$base_ref"; then
        err "Fichiers protégés modifiés pour l'issue #${issue_number}, rollback"
        local touched_files
        touched_files=$(git diff --name-only "${base_ref}..HEAD" || echo "")
        local forbidden_comment
        forbidden_comment=$(cat <<FORBIDDEN
## Worker AI Pipeline — fichiers protégés modifiés

Le worker a tenté de modifier des fichiers verrouillés par \`FORBIDDEN_PATTERNS\` (voir \`scripts/ai_pipeline/config.sh\`). La branche a été supprimée et **aucune PR n'a été créée**.

### Fichiers touchés par l'agent IA

\`\`\`
${touched_files}
\`\`\`

**Action** : reformule l'issue pour cibler des fichiers non protégés, ou fais la correction à la main puis ferme l'issue. Pour relancer, remets le label \`Propose_AI_PR\`.

> Tag \`Propose_AI_PR\` retiré pour éviter les ré-exécutions en boucle.
FORBIDDEN
)
        gh issue comment "$issue_number" --body "$forbidden_comment" 2>&1 | tee -a "$LOG_FILE" || true
        gh issue edit "$issue_number" \
            --remove-label "Propose_AI_PR" \
            --add-label "ai-failed-forbidden-files" \
            2>&1 | tee -a "$LOG_FILE" || warn "Échec swap labels pour issue #${issue_number}"
        rollback "$branch_name" || true
        return_to_branch "$original_branch" || true
        return 0
    fi

    # Push et créer la PR (les tests sont délégués au CI/CD GitHub)
    git push "$REPO_REMOTE" "$branch_name" 2>&1 | tee -a "$LOG_FILE" || {
        err "git push a échoué pour l'issue #${issue_number}"
        return_to_branch "$original_branch" || true
        return 1
    }

    local commit_log
    commit_log=$(git log --oneline "${base_ref}..HEAD")
    local changed_files
    changed_files=$(git diff --stat "${base_ref}..HEAD")

    local corrections_list=""
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        corrections_list="${corrections_list}- \`${line}\`
"
    done <<< "$commit_log"

    # Extraire le bloc CONSEQUENCES_START...CONSEQUENCES_END depuis la sortie de l'agent IA
    local ai_summary
    ai_summary=$(echo "$ai_output" | sed -n '/CONSEQUENCES_START/,/CONSEQUENCES_END/p' \
        | grep -v 'CONSEQUENCES_START\|CONSEQUENCES_END' || echo "")

    local consequences_section=""
    if [[ -n "$ai_summary" ]]; then
        consequences_section="## Analyse de conséquences

${ai_summary}
"
    fi

    # Rappel de l'issue dans la PR : titre + extrait du corps tronqué
    local issue_body
    issue_body=$(gh issue view "$issue_number" --json body --jq '.body' 2>/dev/null || echo "")
    local issue_excerpt="$issue_body"
    if [[ ${#issue_excerpt} -gt 800 ]]; then
        issue_excerpt="${issue_excerpt:0:800}…"
    fi

    # Propager les labels de l'issue sur la PR (sauf Propose_AI_PR : il est
    # remplacé par MR_ready sur l'issue elle-même, et n'a pas de sens sur la PR)
    local -a issue_label_args=()
    local -a _labels_arr=()
    IFS=',' read -ra _labels_arr <<< "$issue_labels"
    local lbl
    for lbl in "${_labels_arr[@]}"; do
        [[ -z "$lbl" || "$lbl" == "Propose_AI_PR" ]] && continue
        issue_label_args+=(--label "$lbl")
    done

    local agent_label
    agent_label=$(ensure_ai_agent_pr_label)

    local pr_body
    pr_body=$(cat <<PRBODY
## Correction automatique - Issue #${issue_number}

Closes #${issue_number}

**Profil d'analyse** : \`${profile}\`
**Date d'exécution** : $(date '+%Y-%m-%d %H:%M')

## Rappel de l'issue

**${issue_title}**

${issue_excerpt}

## Corrections apportées

${corrections_list}

## Fichiers modifiés

\`\`\`
${changed_files}
\`\`\`

${consequences_section}
## Checklist pour le reviewer

- [ ] Les corrections sont pertinentes et justifiées
- [ ] Pas de régression fonctionnelle introduite
- [ ] Aucun fichier sensible n'a été modifié
- [ ] Les tests passent correctement

---
> Généré automatiquement par AI Pipeline ($(ai_agent_label)) - **Review humaine obligatoire avant merge**
PRBODY
)

    # PR ouverte (pas en brouillon) + label pipeline + labels hérités de l'issue
    local pr_url
    pr_url=$(gh pr create \
        --base "$BASE_BRANCH" \
        --head "$branch_name" \
        --title "[AI][${profile}] Correction issue #${issue_number} - ${issue_title}" \
        --body "$pr_body" \
        --label "$PR_LABEL" \
        --label "$agent_label" \
        "${issue_label_args[@]}" \
        2>&1) || {
        err "Échec création PR pour issue #${issue_number}: $pr_url"
        return_to_branch "$original_branch" || true
        return 0
    }

    ok "PR créée: $pr_url"

    # Swap les labels sur l'issue (non bloquant)
    gh issue edit "$issue_number" \
        --remove-label "Propose_AI_PR" \
        --add-label "MR_ready" \
        2>&1 | tee -a "$LOG_FILE" || warn "Échec swap labels pour issue #${issue_number}"
    ok "Issue #${issue_number}: Propose_AI_PR -> MR_ready"

    # Retour sur la branche d'origine
    return_to_branch "$original_branch" || true

    notify "success" "Worker: PR créée pour issue #${issue_number}" "$pr_url"
    return 0
}

main_worker() {
    header "AI Pipeline - Mode WORKER"
    log "Log: $LOG_FILE"

    # 1. Prérequis
    check_prerequisites

    # S'assurer que les labels existent
    ensure_label "Propose_AI_PR" "5319e7" "Demande de PR automatique par IA"
    ensure_label "MR_ready" "0e8a16" "PR créée par IA, prête pour review"
    ensure_label "ai-failed-forbidden-files" "b60205" "Worker a touché un fichier protégé - intervention humaine requise"
    ensure_label "ai-failed-no-changes" "cccccc" "Worker n'a produit aucune modification - issue à clarifier"

    # 2. Chercher les issues avec le tag Propose_AI_PR
    local issues_json
    issues_json=$(gh issue list --state open --limit 1000 --label "Propose_AI_PR" \
        --json number,title,labels \
        --template '{{range .}}{{.number}}|{{.title}}|{{range .labels}}{{.name}},{{end}}{{"\n"}}{{end}}' \
        2>/dev/null || echo "")

    if [[ -z "$issues_json" ]]; then
        ok "Aucune issue avec le tag Propose_AI_PR"
        exit 0
    fi

    local issue_count
    issue_count=$(echo "$issues_json" | grep -c '.' || echo 0)
    log "${issue_count} issue(s) à traiter"

    # Charger le profil worker une fois
    local worker_profile
    worker_profile=$(cat "${PROFILES_DIR}/large_issue/refactor.md")

    # 3. Traiter chaque issue
    # On charge les lignes dans un tableau et on itère dessus plutôt qu'avec
    # `while read <<<` : une sous-commande (agent IA, git, gh…) peut consommer
    # stdin et drainer le here-string, faisant sortir la boucle après 1 seule
    # itération. Avec un `for` sur un tableau, chaque itération fait son
    # propre `read <<<` sur une ligne isolée → pas de stdin partagé.
    local -a issues_lines=()
    mapfile -t issues_lines <<< "$issues_json"

    local processed=0 skipped_on_error=0
    local line
    for line in "${issues_lines[@]}"; do
        [[ -z "$line" ]] && continue

        local issue_number issue_title issue_labels
        IFS='|' read -r issue_number issue_title issue_labels <<< "$line"
        [[ -z "$issue_number" ]] && continue

        if _worker_process_issue "$issue_number" "$issue_title" "$issue_labels" "$worker_profile"; then
            processed=$((processed + 1))
        else
            skipped_on_error=$((skipped_on_error + 1))
            warn "Issue #${issue_number}: erreur inattendue, passage à la suivante"
            # Safety: revenir sur la branche de base pour la prochaine itération
            return_to_branch "$BASE_BRANCH" || true
        fi
    done

    header "Worker terminé"
    log "Issues traitées: ${processed} / ${issue_count}"
    [[ $skipped_on_error -gt 0 ]] && warn "${skipped_on_error} issue(s) sautée(s) sur erreur"
    log "Log complet: $LOG_FILE"
}
