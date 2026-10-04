#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode FIX (corrections rapides, crée des PR)
# ============================================================================

build_fix_prompt() {
    local module_paths="$1"
    local issue_context=""

    if [[ -n "$ISSUE_NUMBER" ]]; then
        # Une issue illisible n'est pas une consigne : la phrase « Impossible de
        # charger l'issue » partait autrefois dans le prompt à sa place.
        issue_context=$(gh_query gh issue view "$ISSUE_NUMBER" --json number,title,body,labels,comments \
            --template '## Issue #{{.number}}: {{.title}}

{{.body}}

### Labels
{{range .labels}}- {{.name}}
{{end}}
### Commentaires
{{range .comments}}---
{{.body}}
{{end}}') || return 1
    fi

    cat <<PROMPT
${PROFILE_CONTENT}

$(ai_project_context)

${issue_context:+## Contexte Issue GitHub

${issue_context}
}
## Périmètre d'analyse

Concentre ton analyse sur les modules suivants : ${module_paths}
Tu peux lire n'importe quel fichier du projet si nécessaire (contrats, faits, événements des autres facultés, frontend…), mais ne corrige que le code des modules ci-dessus.
$(module_scope_note "$module_paths")

$(ai_write_constraints)

$(ai_test_policy write)
PROMPT
}

main_fix() {
    header "AI Pipeline - Mode FIX"
    log "Profil: ${PROFILE:-issue-driven}"
    log "Issue: ${ISSUE_NUMBER:-aucune}"
    log "Log: $LOG_FILE"

    [[ "$DRY_RUN" == true ]] && warn "Mode dry-run - aucune action réelle"

    # 1. Prérequis
    check_prerequisites

    # 2. Vérifier les PR existantes
    if [[ -n "$ISSUE_NUMBER" ]]; then
        if check_existing_issue_pr "$ISSUE_NUMBER"; then
            warn "Abandon - merger ou fermer la PR existante d'abord."
            exit "$EXIT_NOTHING"
        fi
        ok "Aucune PR en doublon pour l'issue #${ISSUE_NUMBER}"
    fi

    # 3. Résoudre les modules
    local module_paths
    if [[ "$MODULES" == "all" && -z "$ISSUE_NUMBER" ]]; then
        local picked
        picked=$(pick_module pr "$PROFILE")
        if [[ -z "$picked" ]]; then
            ok "Tous les modules ont déjà une PR '${PROFILE}' ouverte. Rien à faire."
            exit "$EXIT_NOTHING"
        fi
        MODULES="$picked"
        log "Module choisi automatiquement: $picked"
        module_paths="$picked"
    else
        module_paths=$(resolve_modules "$MODULES") || exit "$EXIT_FAIL"
    fi
    report_set module "$module_paths"
    log "Modules ciblés: $module_paths"

    local prompt
    if ! prompt=$(build_fix_prompt "$module_paths"); then
        err "Impossible de construire le prompt (issue #${ISSUE_NUMBER} illisible ?)"
        exit "$EXIT_FAIL"
    fi

    # 4. Créer la branche
    local branch_name
    branch_name=$(make_branch_name)
    log "Branche: $branch_name"

    if [[ "$DRY_RUN" == true ]]; then
        log "Prompt qui serait envoyé:"
        echo "$prompt"
        ok "Dry-run terminé"
        exit "$EXIT_OK"
    fi

    ensure_workspace || exit "$EXIT_FAIL"
    start_task_branch "$branch_name" || exit "$EXIT_FAIL"
    ok "Branche $branch_name créée sur ${BASE_REF}"

    local base_ref
    base_ref=$(git rev-parse HEAD)

    # 5. Lancer l'agent IA
    header "Lancement IA : ${PROFILE:-issue} sur ${module_paths}"
    local start_time
    start_time=$(date +%s)

    local ai_exit=0 ai_out ai_output
    # Background + wait : permet au trap Ctrl+C de s'exécuter sans attendre la fin de l'agent IA
    ai_out=$(mktemp)
    run_ai_agent "write" "$prompt" "$ai_out" &
    wait $! || ai_exit=$?
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
        exit "$EXIT_FAIL"
    fi

    ok "Analyse IA terminée (${PROFILE}/${module_paths} en ${elapsed}s)"

    # 6. Vérifier les commits
    local commit_count
    if ! commit_count=$(check_ai_commits "$base_ref"); then
        err "Impossible de finaliser les commits IA"
        rollback "$branch_name"
        notify "failure" "Fix ${PROFILE} sur ${module_paths} échoué - commit IA impossible"
        exit "$EXIT_FAIL"
    fi

    if [[ "$commit_count" -eq 0 ]]; then
        warn "Aucune modification effectuée par l'IA"
        finish_task_branch "$branch_name" || true
        notify "success" "Analyse ${PROFILE} - Aucune modification nécessaire"
        exit "$EXIT_NO_RESULT"
    fi

    # 7. Vérifier les fichiers interdits
    if ! check_forbidden_files "$base_ref"; then
        err "L'IA a modifié des fichiers protégés. Annulation."
        rollback "$branch_name"
        notify "failure" "Analyse ${PROFILE} - Fichiers protégés modifiés"
        exit "$EXIT_FAIL"
    fi
    ok "Vérification fichiers protégés: OK (${commit_count} commit(s))"

    # 8. Push et PR
    local pr_url=""
    if [[ "$NO_CREATE" == true ]]; then
        warn "Push et PR désactivés (--no-create)"
        log "Les modifications restent sur la branche locale: $branch_name"
        finish_task_branch "$branch_name" keep || true
    else
        header "Push et Pull Request"
        if ! git push --quiet "$REPO_REMOTE" "$branch_name" >> "$LOG_FILE" 2>&1; then
            err "git push a échoué (voir $LOG_FILE) - branche locale conservée : $branch_name"
            finish_task_branch "$branch_name" keep || true
            notify "failure" "Fix ${PROFILE} sur ${module_paths} - push en échec"
            exit "$EXIT_FAIL"
        fi
        ok "Push effectué"
        if ! pr_url=$(create_pull_request "$branch_name" "$base_ref"); then
            finish_task_branch "$branch_name" || true
            notify "failure" "Fix ${PROFILE} sur ${module_paths} - branche poussée mais PR en échec (${branch_name})"
            exit "$EXIT_FAIL"
        fi
        finish_task_branch "$branch_name" || true
    fi

    # 9. Notifications
    notify "success" "Analyse ${PROFILE:-issue #$ISSUE_NUMBER} terminée" "$pr_url"

    header "Pipeline terminé avec succès"
    log "Branche: $branch_name"
    [[ -n "$pr_url" ]] && log "PR: $pr_url"
    log "Log complet: $LOG_FILE"
    exit "$EXIT_OK"
}
