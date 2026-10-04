#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode WORKER (traite les issues taggées Propose_AI_PR)
# ============================================================================

# Dernières lignes de la réponse de l'agent, pour un commentaire d'issue.
_agent_conclusion() {
    local output="$1"
    local excerpt
    excerpt=$(tail -n 60 <<< "$output")
    if (( ${#excerpt} > 4000 )); then
        excerpt="…${excerpt: -4000}"
    fi
    printf '%s' "$excerpt"
}

# Retire Propose_AI_PR d'une issue, pose un label d'échec et explique pourquoi.
_worker_park_issue() {
    local issue_number="$1" label="$2" body="$3"
    gh issue comment "$issue_number" --body "$body" >> "$LOG_FILE" 2>&1 \
        || warn "Commentaire impossible sur l'issue #${issue_number}"
    gh issue edit "$issue_number" \
        --remove-label "Propose_AI_PR" \
        --add-label "$label" \
        >> "$LOG_FILE" 2>&1 || warn "Échec swap labels pour issue #${issue_number}"
}

# Traite une seule issue. Retourne 0 si l'issue est prise en charge (avec ou
# sans modifications, ou sur une erreur « attendue » comme un timeout IA),
# non-zéro si une commande critique du pipeline (git, gh) échoue.
#
# Attention : appelée dans un `if`, cette fonction s'exécute SANS `set -e`
# (bash le suspend dans un contexte conditionnel). Chaque commande critique est
# donc vérifiée explicitement.
_worker_process_issue() {
    local issue_number="$1"
    local issue_title="$2"
    local issue_labels="$3"
    local worker_profile="$4"

    header "Traitement issue #${issue_number}: ${issue_title}"

    # Déterminer le type depuis le label de profil `ai-<profil>` (préfixe de
    # commit, titre de la PR). Une proposition (features, amelioration)
    # validée à la main arrive ici comme les autres.
    local profile="bugs" candidate
    for candidate in security quality amelioration features bugs; do
        if [[ ",${issue_labels}," == *",ai-${candidate},"* ]]; then
            profile="$candidate"
            break
        fi
    done
    log "Type déduit: $profile"
    PROFILE="$profile"
    ISSUE_NUMBER="$issue_number"

    # Une PR déjà ouverte pour cette issue est fermée puis refaite : remettre
    # Propose_AI_PR sur une issue, c'est demander une nouvelle version.
    local existing_pr
    if ! existing_pr=$(open_prs_with_branch_prefix "${BRANCH_PREFIX}/issue-${issue_number}-"); then
        err "Impossible de vérifier les PR existantes de l'issue #${issue_number}"
        return 1
    fi
    local pr_num pr_branch pr_url
    while IFS='|' read -r pr_num pr_branch pr_url; do
        [[ -z "$pr_num" ]] && continue
        if [[ "$DRY_RUN" == true ]]; then
            log "Dry-run: la PR existante #${pr_num} serait fermée"
            continue
        fi
        warn "PR existante #${pr_num} trouvée, fermeture pour re-création..."
        gh pr close "$pr_num" --delete-branch \
            --comment "Fermée automatiquement par AI Pipeline (re-création demandée via Propose_AI_PR)" \
            >> "$LOG_FILE" 2>&1 || warn "Fermeture de la PR #${pr_num} en échec"
        git branch -q -D "$pr_branch" >> "$LOG_FILE" 2>&1 || true
        ok "PR #${pr_num} fermée et branche $pr_branch supprimée"
    done <<< "$existing_pr"

    # Contenu complet de l'issue (titre + body + commentaires). Une issue
    # illisible n'est pas une consigne : on la saute plutôt que d'envoyer à
    # l'agent la phrase « Impossible de charger l'issue ».
    local issue_full
    if ! issue_full=$(gh_query gh issue view "$issue_number" \
        --json number,title,body,comments \
        --template '## Issue #{{.number}}: {{.title}}

{{.body}}

{{if .comments}}## Commentaires des reviewers
{{range .comments}}
---
{{.body}}
{{end}}{{end}}'); then
        err "Issue #${issue_number} illisible - sautée"
        return 1
    fi

    local branch_name
    branch_name="${BRANCH_PREFIX}/issue-${issue_number}-$(date +%Y%m%d-%H%M%S)"
    log "Branche: $branch_name"

    if [[ "$DRY_RUN" == true ]]; then
        log "Dry-run: issue #${issue_number} serait traitée"
        return 0
    fi

    start_task_branch "$branch_name" || return 1

    local base_ref
    base_ref=$(git rev-parse HEAD)

    local prompt
    prompt=$(cat <<PROMPT
${worker_profile}

$(ai_project_context)

## Contexte : Issue GitHub à corriger

${issue_full}

## Périmètre

Tu travailles sur l'ensemble du projet (hors fichiers protégés). Corrige le problème décrit dans l'issue ci-dessus, en tenant compte des commentaires des reviewers s'il y en a.

Si le problème n'existe plus dans le code actuel (déjà corrigé, code disparu), ne modifie rien et dis-le clairement dans ton résumé, avec le commit ou le fichier qui le prouve : ta réponse sera recopiée sur l'issue.

$(ai_write_constraints)

$(ai_test_policy write)
PROMPT
)

    # Lancer l'agent IA (background + wait pour que Ctrl+C soit interceptable)
    log "Lancement IA pour issue #${issue_number} (${profile})..."
    local start_time ai_exit=0 ai_out ai_output
    start_time=$(date +%s)
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
        err "$(ai_agent_label) a échoué sur issue #${issue_number} (exit: $ai_exit - ${reason})"
        rollback "$branch_name" || true
        return 0
    fi

    ok "IA terminée pour issue #${issue_number} en ${elapsed}s"

    # Vérifier les commits
    local commit_count
    if ! commit_count=$(check_ai_commits "$base_ref"); then
        err "Impossible de finaliser les commits IA pour l'issue #${issue_number}"
        rollback "$branch_name" || true
        return 0
    fi

    if [[ "$commit_count" -eq 0 ]]; then
        warn "Aucune modification pour l'issue #${issue_number}"
        # La réponse de l'agent part sur l'issue : « déjà corrigé par #213 » et
        # « l'issue est trop vague » appelaient deux suites différentes, et le
        # commentaire générique d'avant ne laissait pas les distinguer.
        local conclusion
        conclusion=$(_agent_conclusion "$ai_output")
        _worker_park_issue "$issue_number" "ai-failed-no-changes" "$(cat <<NOCHANGE
## Worker AI Pipeline — aucune modification produite

Le worker a analysé cette issue mais n'a généré **aucun commit**. Sa conclusion :

<details open><summary>Réponse de l'agent ($(ai_agent_label))</summary>

${conclusion}

</details>

**Action** : si le problème est déjà corrigé, ferme l'issue. Sinon, précise-la (fichier, ligne, comportement attendu) puis remets le label \`Propose_AI_PR\` pour relancer.

> Tag \`Propose_AI_PR\` retiré pour éviter les ré-exécutions en boucle.
NOCHANGE
)"
        finish_task_branch "$branch_name" || true
        return 0
    fi

    # Vérifier fichiers interdits
    if ! check_forbidden_files "$base_ref"; then
        err "Fichiers protégés modifiés pour l'issue #${issue_number}, rollback"
        local touched_files
        touched_files=$(git diff --name-only "${base_ref}..HEAD" || echo "")
        _worker_park_issue "$issue_number" "ai-failed-forbidden-files" "$(cat <<FORBIDDEN
## Worker AI Pipeline — fichiers protégés modifiés

Le worker a tenté de modifier des fichiers verrouillés par \`FORBIDDEN_PATTERNS\` (voir \`scripts/ai_pipeline/config.sh\`). La branche a été supprimée et **aucune PR n'a été créée**.

### Fichiers touchés par l'agent IA

\`\`\`
${touched_files}
\`\`\`

**Action** : reformule l'issue pour cibler des fichiers non protégés, ou fais la correction à la main puis ferme l'issue. Pour relancer, remets le label \`Propose_AI_PR\`.

> Tag \`Propose_AI_PR\` retiré pour éviter les ré-exécutions en boucle.
FORBIDDEN
)"
        rollback "$branch_name" || true
        return 0
    fi

    # Push et PR
    if ! git push --quiet "$REPO_REMOTE" "$branch_name" >> "$LOG_FILE" 2>&1; then
        err "git push a échoué pour l'issue #${issue_number} - branche locale conservée : $branch_name"
        finish_task_branch "$branch_name" keep || true
        return 1
    fi

    local commit_log changed_files
    commit_log=$(git log --oneline "${base_ref}..HEAD")
    changed_files=$(git diff --stat "${base_ref}..HEAD")

    local corrections_list="" line
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        corrections_list+="- \`${line}\`"$'\n'
    done <<< "$commit_log"

    # Bloc CONSEQUENCES_START...CONSEQUENCES_END de la sortie de l'agent
    local ai_summary consequences_section=""
    ai_summary=$(sed -n '/CONSEQUENCES_START/,/CONSEQUENCES_END/p' <<< "$ai_output" \
        | grep -v 'CONSEQUENCES_START\|CONSEQUENCES_END' || true)
    if [[ -n "$ai_summary" ]]; then
        consequences_section="## Analyse de conséquences

${ai_summary}
"
    fi

    # Rappel de l'issue dans la PR : extrait du corps tronqué
    local issue_body issue_excerpt
    issue_body=$(gh issue view "$issue_number" --json body --jq '.body' 2>/dev/null || echo "")
    issue_excerpt="$issue_body"
    if [[ ${#issue_excerpt} -gt 800 ]]; then
        issue_excerpt="${issue_excerpt:0:800}…"
    fi

    # Propager les labels de l'issue sur la PR (sauf Propose_AI_PR : il est
    # remplacé par MR_ready sur l'issue elle-même, et n'a pas de sens sur la PR)
    local -a issue_label_args=() _labels_arr=()
    local lbl
    IFS=',' read -ra _labels_arr <<< "$issue_labels"
    for lbl in "${_labels_arr[@]}"; do
        [[ -z "$lbl" || "$lbl" == "Propose_AI_PR" ]] && continue
        issue_label_args+=(--label "$lbl")
    done

    ensure_label "$PR_LABEL" "0e8a16" "PR proposée par AI Pipeline"
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
        finish_task_branch "$branch_name" || true
        return 0
    }
    pr_url=$(tail -n 1 <<< "$pr_url")
    ok "PR créée: $pr_url"

    gh issue edit "$issue_number" \
        --remove-label "Propose_AI_PR" \
        --add-label "MR_ready" \
        >> "$LOG_FILE" 2>&1 || warn "Échec swap labels pour issue #${issue_number}"
    ok "Issue #${issue_number}: Propose_AI_PR -> MR_ready"

    finish_task_branch "$branch_name" || true

    notify "success" "Worker: PR créée pour issue #${issue_number}" "$pr_url"
    WORKER_PRS_CREATED=$(( ${WORKER_PRS_CREATED:-0} + 1 ))
    return 0
}

main_worker() {
    header "AI Pipeline - Mode WORKER"
    log "Log: $LOG_FILE"

    # 1. Prérequis
    check_prerequisites

    # 2. Chercher les issues avec le tag Propose_AI_PR. Une requête en échec
    #    n'est pas « aucune issue » (cf. gh_query).
    local issues_list
    if ! issues_list=$(gh_query gh issue list --state open --limit 1000 --label "Propose_AI_PR" \
        --json number,title,labels \
        --template '{{range .}}{{.number}}{{"\t"}}{{.title}}{{"\t"}}{{range .labels}}{{.name}},{{end}}{{"\n"}}{{end}}'); then
        err "Impossible de lister les issues Propose_AI_PR"
        exit "$EXIT_FAIL"
    fi

    local -a issues_lines=()
    mapfile -t issues_lines < <(grep . <<< "$issues_list" || true)

    if [[ ${#issues_lines[@]} -eq 0 ]]; then
        ok "Aucune issue avec le tag Propose_AI_PR"
        exit "$EXIT_NOTHING"
    fi
    log "${#issues_lines[@]} issue(s) à traiter"

    if [[ "$DRY_RUN" != true ]]; then
        # S'assurer que les labels existent
        ensure_label "Propose_AI_PR" "5319e7" "Demande de PR automatique par IA"
        ensure_label "MR_ready" "0e8a16" "PR créée par IA, prête pour review"
        ensure_label "ai-failed-forbidden-files" "b60205" "Worker a touché un fichier protégé - intervention humaine requise"
        ensure_label "ai-failed-no-changes" "cccccc" "Worker n'a produit aucune modification - issue à clarifier"
        ensure_workspace || exit "$EXIT_FAIL"
    fi

    # Charger le profil worker une fois
    local worker_profile
    worker_profile=$(cat "${PROFILES_DIR}/large_issue/refactor.md")

    # 3. Traiter chaque issue. Les lignes sont chargées dans un tableau plutôt
    # que lues par `while read <<<` : une sous-commande (agent IA, git, gh…)
    # peut consommer stdin et drainer le here-string, faisant sortir la boucle
    # après une seule itération.
    WORKER_PRS_CREATED=0
    local processed=0 skipped_on_error=0 line
    for line in "${issues_lines[@]}"; do
        local issue_number issue_title issue_labels
        # Séparateur tabulation : un titre d'issue contenant « | » décalait les
        # champs, et ses labels partaient dans le titre.
        IFS=$'\t' read -r issue_number issue_title issue_labels <<< "$line"
        [[ -z "$issue_number" ]] && continue

        if _worker_process_issue "$issue_number" "$issue_title" "$issue_labels" "$worker_profile"; then
            processed=$((processed + 1))
        else
            skipped_on_error=$((skipped_on_error + 1))
            warn "Issue #${issue_number}: erreur inattendue, passage à la suivante"
            [[ "$DRY_RUN" != true ]] && { workspace_reset "après l'issue #${issue_number}" || true; }
        fi
    done

    header "Worker terminé"
    log "Issues traitées: ${processed} / ${#issues_lines[@]} - PR créées: ${WORKER_PRS_CREATED}"
    [[ $skipped_on_error -gt 0 ]] && warn "${skipped_on_error} issue(s) sautée(s) sur erreur"
    log "Log complet: $LOG_FILE"

    if (( WORKER_PRS_CREATED > 0 )); then
        exit "$EXIT_OK"
    elif (( processed == 0 )); then
        exit "$EXIT_FAIL"
    fi
    exit "$EXIT_NO_RESULT"
}
