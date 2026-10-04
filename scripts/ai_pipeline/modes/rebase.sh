#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode REBASE
# ============================================================================
# Examine les PRs ouvertes créées par le pipeline (préfixe de branche ai/) :
#   - PRs en conflit avec main → rebase automatique via l'agent IA
#   - PRs encore mergeable    → check de pertinence : si l'issue d'origine
#     n'est plus pertinente (problème déjà résolu, fichiers disparus, etc.),
#     on ferme la PR et toutes les issues liées (Closes/Fixes/Resolves #N)
#
# Le mode ne crée AUCUNE nouvelle issue ni nouvelle PR. Il maintient l'état
# existant uniquement.
# ============================================================================

# PRs ouvertes dont la branche commence par BRANCH_PREFIX/, en tableau JSON.
# Filtrées par jq et non par `--search head:` : l'API Search ne suit pas les
# renommages de dépôt, et son échec était lu comme « aucune PR ».
_rebase_list_pipeline_prs() {
    gh_query gh pr list --state open --limit 1000 \
        --json number,headRefName,title,body,mergeable,url \
        --jq "[.[] | select(.headRefName | startswith(\"${BRANCH_PREFIX}/\"))]"
}

# Résout un statut mergeable=UNKNOWN en interrogeant `gh pr view` (qui force
# GitHub à calculer le merge state, lazy-computed après ouverture/push).
# Retourne sur stdout : MERGEABLE | CONFLICTING | UNKNOWN
_rebase_resolve_mergeable() {
    local pr_num="$1"
    local attempts=3 delay=2 i mergeable
    for ((i = 1; i <= attempts; i++)); do
        mergeable=$(gh pr view "$pr_num" --json mergeable -q .mergeable 2>/dev/null || echo "UNKNOWN")
        if [[ "$mergeable" == "MERGEABLE" || "$mergeable" == "CONFLICTING" ]]; then
            echo "$mergeable"
            return 0
        fi
        sleep "$delay"
    done
    echo "UNKNOWN"
}

# Extrait les numéros d'issues que la PR fermerait (Closes/Fixes/Resolves #N)
_rebase_extract_closing_issues() {
    local body="$1"
    grep -oiE '(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#[0-9]+' <<< "$body" \
        | grep -oE '#[0-9]+' | tr -d '#' | sort -u || true
}

# La branche distante contient-elle la pointe de la branche de base ? C'est la
# preuve qu'un rebase a eu lieu ET a été poussé — l'exit code de l'agent ne
# prouvait que l'absence de plantage.
_rebase_branch_is_up_to_date() {
    local branch="$1"
    git fetch --quiet "$REPO_REMOTE" "$BASE_BRANCH" "$branch" >> "$LOG_FILE" 2>&1 || return 1
    git merge-base --is-ancestor "$BASE_REF" "${REPO_REMOTE}/${branch}"
}

# Demande à l'IA de rebase une branche en conflit sur BASE_BRANCH
_rebase_rebase_pr() {
    local pr_num="$1" branch="$2"

    header "Rebase de la PR #${pr_num} (${branch})"

    local prompt
    prompt=$(cat <<PROMPT
La PR #${pr_num} (branche \`${branch}\`) est en conflit avec \`${BASE_BRANCH}\`.

$(ai_project_context)

## Tâche

Rebase la branche \`${branch}\` sur \`${BASE_REF}\` et résous les conflits en préservant l'intention de la PR. Tu es dans un worktree dédié au pipeline, en tête détachée.

## Étapes attendues

1. \`git fetch ${REPO_REMOTE} ${BASE_BRANCH} ${branch}\`
2. \`git checkout -B ${branch} ${REPO_REMOTE}/${branch}\`
3. \`git rebase ${BASE_REF}\`
4. Pour chaque conflit :
   - Lis les deux versions
   - Identifie l'intention de la PR (commits originaux)
   - Résous en gardant cette intention sans casser les changements de ${BASE_BRANCH}
   - \`git add <fichier>\`
   - \`git rebase --continue\`
5. Une fois propre : \`git push --force-with-lease ${REPO_REMOTE} ${branch}\`

## Si rebase impossible

Si les conflits sont trop massifs ou si l'intention de la PR est devenue incompatible avec ${BASE_BRANCH} (refactor structurel, suppression de fichiers ciblés, etc.) :
- \`git rebase --abort\`
- Réponds en première ligne EXACTEMENT : \`REBASE_ABORTED: <raison courte en français>\`

## Contraintes

- N'effectue AUCUN \`git push --force\` sans \`--with-lease\`
- Ne touche PAS aux autres branches, ne pousse rien d'autre que \`${branch}\`
- N'exécute aucun test (une vérification \`ruff\`/\`tsc\` ciblée sur un fichier en conflit est permise)
- Réponds en français
PROMPT
)

    local ai_out ai_exit=0 output
    ai_out=$(mktemp)
    run_ai_agent "write" "$prompt" "$ai_out" &
    wait $! || ai_exit=$?
    output=$(cat "$ai_out")
    echo "$output" >> "$LOG_FILE"
    rm -f "$ai_out"

    local outcome=1
    if grep -qE '^REBASE_ABORTED' <<< "$output"; then
        local reason
        reason=$(grep -m1 '^REBASE_ABORTED' <<< "$output" | sed 's/^REBASE_ABORTED:[[:space:]]*//')
        warn "Rebase abandonné pour #${pr_num} : ${reason}"
        gh pr comment "$pr_num" \
            --body "AI Pipeline n'a pas pu rebase automatiquement cette PR. Raison : ${reason}. Intervention manuelle requise." \
            >> "$LOG_FILE" 2>&1 || true
    elif [[ $ai_exit -ne 0 ]]; then
        warn "Agent IA a échoué (exit $ai_exit) pour le rebase de #${pr_num}"
    elif _rebase_branch_is_up_to_date "$branch"; then
        ok "PR #${pr_num} rebasée"
        outcome=0
    else
        warn "L'agent dit avoir fini, mais ${REPO_REMOTE}/${branch} ne contient pas ${BASE_REF} : rebase non poussé"
    fi

    # Le worktree revient sur la base ; la copie locale de la branche part
    # (elle vit sur le distant).
    workspace_reset "après le rebase de #${pr_num}" || true
    git branch -q -D "$branch" >> "$LOG_FILE" 2>&1 || true
    return $outcome
}

# Demande à l'IA si la PR est encore pertinente. Retourne une ligne :
#   KEEP: <raison>   → garder
#   STALE: <raison>  → fermer + fermer issues liées
_rebase_check_pr_relevance() {
    local pr_num="$1" title="$2" body="$3"

    # Diff borné à 400 lignes. `gh pr diff | head` échouait sous pipefail dès
    # que le diff dépassait la borne (SIGPIPE), et « (diff non disponible) »
    # s'ajoutait au diff tronqué.
    local diff
    diff=$(gh pr diff "$pr_num" 2>/dev/null) || diff="(diff non disponible)"
    diff=$(head -n 400 <<< "$diff")

    local issue_refs issue_section="" n
    issue_refs=$(_rebase_extract_closing_issues "$body")
    if [[ -n "$issue_refs" ]]; then
        for n in $issue_refs; do
            local issue_data
            issue_data=$(gh issue view "$n" --json state,title,body \
                --template '- État: {{.state}}
- Titre: {{.title}}
- Body:
{{.body}}' 2>/dev/null || echo "(issue #${n} introuvable)")
            issue_section+=$'\n### Issue #'"${n}"$'\n'"${issue_data}"$'\n'
        done
    else
        issue_section=$'\n(aucune issue référencée via Closes/Fixes/Resolves dans le body)\n'
    fi

    local prompt
    prompt=$(cat <<PROMPT
Évalue si cette PR du pipeline AI est ENCORE pertinente. Le répertoire courant contient le code actuel de \`${BASE_BRANCH}\`.

## PR #${pr_num} : ${title}

\`\`\`
${body}
\`\`\`

## Issues liées
${issue_section}

## Diff (extrait, max 400 lignes)
\`\`\`diff
${diff}
\`\`\`

## Critères pour STALE (PR à fermer)

Une PR est obsolète si AU MOINS UN de ces points est vrai :
1. Le problème ciblé n'existe plus dans le code actuel de \`${BASE_BRANCH}\`
2. Une autre PR / un autre commit a déjà résolu le même problème
3. Les fichiers ou fonctions ciblées par le diff n'existent plus
4. L'issue référencée est déjà fermée comme résolue par ailleurs

Vérifie en lisant le code actuel.

## Format de réponse OBLIGATOIRE

UNE SEULE LIGNE, l'une des deux exactement :

\`KEEP: <raison courte en français>\`
\`STALE: <raison courte en français>\`

Aucun markdown. Pas de phrase d'introduction. Une seule ligne.
PROMPT
)

    local ai_out ai_exit=0 verdict=""
    ai_out=$(mktemp)
    run_ai_agent "read" "$prompt" "$ai_out" &
    wait $! || ai_exit=$?
    if [[ $ai_exit -eq 0 ]]; then
        # Tolère les accents graves que le modèle recopie parfois du gabarit.
        verdict=$(sed 's/^`//; s/`$//' "$ai_out" | grep -oE '^(KEEP|STALE):.*$' | head -1 || true)
    fi
    rm -f "$ai_out"

    # En cas d'absence de verdict clair, on conserve par défaut (safe)
    [[ -z "$verdict" ]] && verdict="KEEP: verdict IA absent ou illisible (conservation par sécurité)"
    echo "$verdict"
}

main_rebase() {
    header "AI Pipeline - Mode REBASE / Cleanup PRs"
    log "Log: $LOG_FILE"

    check_prerequisites

    local prs_json
    if ! prs_json=$(_rebase_list_pipeline_prs); then
        err "Impossible de lister les PR du pipeline"
        exit "$EXIT_FAIL"
    fi

    local -a pr_numbers=()
    mapfile -t pr_numbers < <(jq -r '.[].number' <<< "$prs_json")

    if [[ ${#pr_numbers[@]} -eq 0 ]]; then
        ok "Aucune PR pipeline ouverte - rien à faire"
        exit "$EXIT_NOTHING"
    fi

    log "${#pr_numbers[@]} PR(s) pipeline ouverte(s) à examiner"

    # L'agent lit le code de la base dans le worktree, et y rebase.
    if [[ "$DRY_RUN" != true ]]; then
        ensure_workspace || exit "$EXIT_FAIL"
    fi

    local rebased=0 closed=0 kept=0 failed=0 pr_num
    for pr_num in "${pr_numbers[@]}"; do
        local branch title body mergeable url
        branch=$(jq -r --argjson n "$pr_num" '.[] | select(.number == $n) | .headRefName' <<< "$prs_json")
        title=$(jq -r --argjson n "$pr_num" '.[] | select(.number == $n) | .title' <<< "$prs_json")
        body=$(jq -r --argjson n "$pr_num" '.[] | select(.number == $n) | .body' <<< "$prs_json")
        mergeable=$(jq -r --argjson n "$pr_num" '.[] | select(.number == $n) | .mergeable' <<< "$prs_json")
        url=$(jq -r --argjson n "$pr_num" '.[] | select(.number == $n) | .url' <<< "$prs_json")

        log ""
        log "─── PR #${pr_num} : ${title}"
        log "    Branche: ${branch} | Mergeable: ${mergeable} | URL: ${url}"

        if [[ "$DRY_RUN" == true ]]; then
            log "    (dry-run : pas d'action)"
            continue
        fi

        # `gh pr list` renvoie souvent mergeable=UNKNOWN car GitHub calcule ce
        # champ paresseusement. On force le calcul via `gh pr view` (avec retry)
        # avant de décider entre rebase et check de pertinence.
        if [[ "$mergeable" == "UNKNOWN" ]]; then
            local resolved
            resolved=$(_rebase_resolve_mergeable "$pr_num")
            if [[ "$resolved" != "UNKNOWN" ]]; then
                log "    Mergeable résolu: ${mergeable} → ${resolved}"
                mergeable="$resolved"
            fi
        fi

        if ! check_ai_tokens; then
            err "Agent IA indisponible - arrêt du rebase"
            break
        fi

        if [[ "$mergeable" == "CONFLICTING" ]]; then
            if _rebase_rebase_pr "$pr_num" "$branch"; then
                rebased=$((rebased + 1))
            else
                failed=$((failed + 1))
            fi
            continue
        fi

        # Cas MERGEABLE / UNKNOWN : check de pertinence
        local verdict
        verdict=$(_rebase_check_pr_relevance "$pr_num" "$title" "$body")
        log "    Verdict: $verdict"

        if [[ "$verdict" == STALE:* ]]; then
            local reason="${verdict#STALE: }"
            warn "Fermeture PR #${pr_num} : ${reason}"

            gh pr close "$pr_num" --delete-branch \
                --comment "Fermée automatiquement par AI Pipeline — PR plus pertinente : ${reason}" \
                >> "$LOG_FILE" 2>&1 || warn "Fermeture de la PR #${pr_num} en échec"

            # Fermer aussi les issues liées
            local n
            for n in $(_rebase_extract_closing_issues "$body"); do
                if gh issue close "$n" \
                    --comment "Fermée automatiquement par AI Pipeline (PR #${pr_num} obsolète) — ${reason}" \
                    >> "$LOG_FILE" 2>&1; then
                    ok "Issue #${n} fermée"
                else
                    warn "Fermeture de l'issue #${n} en échec"
                fi
            done

            closed=$((closed + 1))
        else
            kept=$((kept + 1))
        fi
    done

    header "Mode rebase terminé"
    log "  Rebasées    : $rebased"
    log "  Fermées     : $closed"
    log "  Conservées  : $kept"
    log "  Échecs      : $failed"

    (( rebased + closed > 0 )) && exit "$EXIT_OK"
    (( failed > 0 )) && exit "$EXIT_FAIL"
    exit "$EXIT_NO_RESULT"
}
