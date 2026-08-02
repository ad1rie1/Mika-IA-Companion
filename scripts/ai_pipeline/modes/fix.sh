#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode FIX (corrections rapides, crée des PR)
# ============================================================================

build_fix_prompt() {
    local module_paths="$1"
    local issue_context=""

    if [[ -n "$ISSUE_NUMBER" ]]; then
        issue_context=$(gh issue view "$ISSUE_NUMBER" --json title,body,labels,comments \
            --template '## Issue #{{.number}}: {{.title}}

{{.body}}

### Labels
{{range .labels}}- {{.name}}
{{end}}
### Commentaires
{{range .comments}}---
{{.body}}
{{end}}' 2>/dev/null || echo "Impossible de charger l'issue #${ISSUE_NUMBER}")
    fi

    cat <<PROMPT
${PROFILE_CONTENT}

$(ai_project_context)

${issue_context:+## Contexte Issue GitHub

${issue_context}
}
## Périmètre d'analyse

Concentre ton analyse sur les modules suivants : ${module_paths}
Tu peux lire n'importe quel fichier du projet si nécessaire (imports, dépendances, modèles partagés, etc.), mais ne corrige que le code des modules ci-dessus.

## Contraintes ABSOLUES

1. Tu peux LIRE, MODIFIER des fichiers et exécuter des commandes bash
2. Pour chaque correction, fais un commit séparé avec : git add <fichiers> && git commit -m "prefix: description"
   - Préfixes obligatoires : bug: / security: / feat: selon le type de correction
   - Message de commit en français
   - Exemple : git commit -m "bug: correction du NoneType sur person_id dans le résolveur d'identité"
3. Tu ne dois JAMAIS exécuter : git push, git branch, git checkout, git merge, git rebase, git reset, git stash
4. Tu ne dois JAMAIS exécuter de commandes système dangereuses (rm -rf, etc.)
5. Tu ne dois JAMAIS modifier les fichiers protégés : settings.py, manage.py, */migrations/*, *.env, personality.yaml, data/*, uploads/*, pytest.ini, requirements.txt, package.json
6. Tu ne dois JAMAIS ajouter d'alias ou renommer des fonctions existantes
7. Chaque modification doit être minimale et ciblée
8. Lis TOUJOURS le fichier CLAUDE.md à la racine du projet et respecte ses règles
9. Respecte la politique de tests ci-dessous : pas de nouveaux tests, pas de suite complète, vérification ciblée uniquement

$(ai_test_policy write)
PROMPT
}

main_fix() {
    header "AI Pipeline - Mode FIX"
    log "Profil: ${PROFILE:-issue-driven}"
    log "Issue: ${ISSUE_NUMBER:-aucune}"
    log "Log: $LOG_FILE"

    if [[ "$DRY_RUN" == true ]]; then
        warn "Mode dry-run - aucune action réelle"
    fi

    # 1. Prérequis
    check_prerequisites

    # 2. Vérifier les PR existantes
    if [[ -n "$ISSUE_NUMBER" ]]; then
        if check_existing_issue_pr "$ISSUE_NUMBER"; then
            warn "Abandon - merger ou fermer la PR existante d'abord."
            exit 0
        fi
        ok "Aucune PR en doublon pour l'issue #${ISSUE_NUMBER}"
    fi

    # 3. Résoudre les modules
    local module_paths
    if [[ "$MODULES" == "all" && -z "$ISSUE_NUMBER" ]]; then
        local picked
        picked=$(pick_available_module "$PROFILE")
        if [[ -z "$picked" ]]; then
            ok "Tous les modules ont déjà une PR '${PROFILE}' ouverte. Rien à faire."
            exit 0
        fi
        MODULES="$picked"
        log "Module choisi automatiquement: $picked"
        module_paths="$picked"
    else
        module_paths=$(resolve_modules "$MODULES")
    fi
    log "Modules ciblés: $module_paths"

    # 4. Créer la branche
    local branch_name
    branch_name=$(make_branch_name)
    log "Branche: $branch_name"

    if [[ "$DRY_RUN" == true ]]; then
        log "Prompt qui serait envoyé:"
        build_fix_prompt "$module_paths"
        ok "Dry-run terminé"
        exit 0
    fi

    cd "$PROJECT_ROOT"

    local original_branch
    original_branch=$(git rev-parse --abbrev-ref HEAD)

    # Repartir d'un arbre propre : un reste non commité d'une tâche précédente
    # est emporté par le checkout et se retrouve dans la branche suivante.
    park_dirty_worktree "avant fix ${PROFILE}/${module_paths}" || true

    git checkout "$BASE_BRANCH" 2>&1 | tee -a "$LOG_FILE"
    git pull "$REPO_REMOTE" "$BASE_BRANCH" 2>&1 | tee -a "$LOG_FILE"

    git checkout -b "$branch_name" 2>&1 | tee -a "$LOG_FILE"
    ok "Branche $branch_name créée"

    local base_ref
    base_ref=$(git rev-parse HEAD)

    # 5. Lancer l'agent IA
    header "Lancement IA : ${PROFILE} sur ${module_paths}"
    local start_time
    start_time=$(date +%s)
    local prompt
    prompt=$(build_fix_prompt "$module_paths")

    local ai_exit=0
    local ai_output
    # Background + wait : permet au trap Ctrl+C de s'exécuter sans attendre la fin de l'agent IA
    local ai_out
    ai_out=$(mktemp)
    run_ai_agent "write" "$prompt" "$ai_out" &
    local ai_pid=$!
    wait "$ai_pid" || ai_exit=$?
    ai_output=$(cat "$ai_out")
    rm -f "$ai_out"

    local elapsed=$(( $(date +%s) - start_time ))
    echo "$ai_output" >> "$LOG_FILE"

    if [[ $ai_exit -ne 0 ]]; then
        local reason="erreur inconnue"
        [[ $ai_exit -eq 124 ]] && reason="timeout après ${elapsed}s (max $(ai_agent_timeout)s)"
        err "$(ai_agent_label) a échoué sur ${PROFILE}/${module_paths} (exit: $ai_exit - ${reason})"
        echo "$ai_output" | tail -10
        rollback "$branch_name"
        notify "failure" "Fix ${PROFILE} sur ${module_paths} échoué - ${reason}"
        exit 1
    fi

    ok "Analyse IA terminée (${PROFILE}/${module_paths} en ${elapsed}s)"

    # 6. Vérifier les commits
    local commit_count
    if ! commit_count=$(check_ai_commits "$base_ref"); then
        err "Impossible de finaliser les commits IA"
        rollback "$branch_name"
        notify "failure" "Fix ${PROFILE} sur ${module_paths} échoué - commit IA impossible"
        exit 1
    fi

    if [[ "$commit_count" -eq 0 ]]; then
        warn "Aucune modification effectuée par l'IA"
        return_to_branch "$original_branch" || true
        git branch -D "$branch_name" 2>/dev/null
        notify "success" "Analyse ${PROFILE} - Aucune modification nécessaire"
        exit 0
    fi

    # 7. Vérifier les fichiers interdits
    if ! check_forbidden_files "$base_ref"; then
        err "L'IA a modifié des fichiers protégés. Annulation."
        rollback "$branch_name"
        notify "failure" "Analyse ${PROFILE} - Fichiers protégés modifiés"
        exit 1
    fi
    ok "Vérification fichiers protégés: OK (${commit_count} commit(s))"

    # 8. Push et PR (les tests sont délégués au CI/CD GitHub)
    local pr_url=""
    if [[ "$NO_CREATE" != true ]]; then
        header "Push et Pull Request"
        git push "$REPO_REMOTE" "$branch_name" 2>&1 | tee -a "$LOG_FILE"
        ok "Push effectué"
        pr_url=$(create_pull_request "$branch_name" "$base_ref")
    else
        warn "Push et PR désactivés (--no-create)"
        log "Les modifications restent sur la branche locale: $branch_name"
    fi

    # 10. Retour sur la branche d'origine
    return_to_branch "$original_branch" || true

    # 11. Notifications
    notify "success" "Analyse ${PROFILE} terminée" "$pr_url"

    header "Pipeline terminé avec succès"
    log "Branche: $branch_name"
    [[ -n "$pr_url" ]] && log "PR: $pr_url"
    log "Log complet: $LOG_FILE"
}
