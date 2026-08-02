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

# Liste les PRs ouvertes dont la branche source commence par BRANCH_PREFIX/
_rebase_list_pipeline_prs() {
    gh pr list --state open --limit 1000 \
        --search "head:${BRANCH_PREFIX}/" \
        --json number,headRefName,title,body,mergeable,url \
        2>/dev/null || echo "[]"
}

# Résout un statut mergeable=UNKNOWN en interrogeant `gh pr view` (qui force
# GitHub à calculer le merge state, lazy-computed après ouverture/push).
# Retries quelques fois pour laisser le temps au calcul de se finaliser.
# Retourne sur stdout : MERGEABLE | CONFLICTING | UNKNOWN
_rebase_resolve_mergeable() {
    local pr_num="$1"
    local attempts=3
    local delay=2
    local i mergeable
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
    echo "$body" | grep -oiE '(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#[0-9]+' \
        | grep -oE '#[0-9]+' | tr -d '#' | sort -u
}

# Demande à l'IA de rebase une branche en conflit sur BASE_BRANCH
_rebase_rebase_pr() {
    local pr_num="$1" branch="$2"

    header "Rebase de la PR #${pr_num} (${branch})"

    local prompt
    prompt=$(cat <<PROMPT
La PR #${pr_num} (branche \`${branch}\`) est en conflit avec \`${BASE_BRANCH}\`.

## Tâche

Rebase la branche \`${branch}\` sur \`${REPO_REMOTE}/${BASE_BRANCH}\` et résous les conflits en préservant l'intention de la PR.

## Étapes attendues

1. \`git fetch ${REPO_REMOTE} ${BASE_BRANCH}\`
2. \`git checkout ${branch}\` (ou \`git checkout -b ${branch} ${REPO_REMOTE}/${branch}\` si la branche locale n'existe pas)
3. \`git rebase ${REPO_REMOTE}/${BASE_BRANCH}\`
4. Pour chaque conflit :
   - Lis les deux versions
   - Identifie l'intention de la PR (commits originaux)
   - Résous en gardant cette intention sans casser les changements de main
   - \`git add <fichier>\`
   - \`git rebase --continue\`
5. Une fois propre : \`git push --force-with-lease ${REPO_REMOTE} ${branch}\`

## Si rebase impossible

Si les conflits sont trop massifs ou si l'intention de la PR est devenue incompatible avec main (refactor structurel, suppression de fichiers ciblés, etc.) :
- \`git rebase --abort\`
- \`git checkout ${BASE_BRANCH}\`
- Réponds en première ligne EXACTEMENT : \`REBASE_ABORTED: <raison courte en français>\`

## Contraintes

- N'effectue AUCUN \`git push --force\` sans \`--with-lease\`
- Ne touche PAS aux autres branches
- Ne modifie PAS \`${BASE_BRANCH}\` localement
- Réponds en français
PROMPT
)

    local ai_out
    ai_out=$(mktemp)
    local ai_exit=0
    run_ai_agent "edit" "$prompt" "$ai_out" &
    local ai_pid=$!
    wait "$ai_pid" || ai_exit=$?

    local output
    output=$(cat "$ai_out")
    echo "$output" >> "$LOG_FILE"
    rm -f "$ai_out"

    # S'assurer qu'on n'est pas resté sur la branche de la PR (sécurité)
    cd "$PROJECT_ROOT"
    git checkout "$BASE_BRANCH" 2>/dev/null || true

    if [[ $ai_exit -ne 0 ]]; then
        warn "Agent IA a échoué (exit $ai_exit) pour le rebase de #${pr_num}"
        return 1
    fi

    if grep -qE '^REBASE_ABORTED' <<< "$output"; then
        local reason
        reason=$(grep -m1 '^REBASE_ABORTED' <<< "$output" | sed 's/^REBASE_ABORTED:[[:space:]]*//')
        warn "Rebase abandonné pour #${pr_num} : ${reason}"
        gh pr comment "$pr_num" \
            --body "AI Pipeline n'a pas pu rebase automatiquement cette PR. Raison : ${reason}. Intervention manuelle requise." \
            2>/dev/null || true
        return 1
    fi

    ok "PR #${pr_num} rebasée"
    return 0
}

# Demande à l'IA si la PR est encore pertinente. Retourne une ligne :
#   KEEP: <raison>   → garder
#   STALE: <raison>  → fermer + fermer issues liées
_rebase_check_pr_relevance() {
    local pr_num="$1" title="$2" body="$3"

    local diff
    diff=$(gh pr diff "$pr_num" 2>/dev/null | head -400 || echo "(diff non disponible)")

    local issue_refs
    issue_refs=$(_rebase_extract_closing_issues "$body")

    local issue_section=""
    if [[ -n "$issue_refs" ]]; then
        local n
        for n in $issue_refs; do
            local issue_data
            issue_data=$(gh issue view "$n" --json state,title,body \
                --template '- État: {{.state}}\n- Titre: {{.title}}\n- Body:\n{{.body}}' \
                2>/dev/null || echo "(issue #${n} introuvable)")
            issue_section+=$'\n### Issue #'"${n}"$'\n'"${issue_data}"$'\n'
        done
    else
        issue_section=$'\n(aucune issue référencée via Closes/Fixes/Resolves dans le body)\n'
    fi

    local prompt
    prompt=$(cat <<PROMPT
Évalue si cette PR du pipeline AI est ENCORE pertinente.

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

    local ai_out
    ai_out=$(mktemp)
    local ai_exit=0
    run_ai_agent "read" "$prompt" "$ai_out" &
    local ai_pid=$!
    wait "$ai_pid" || ai_exit=$?

    local verdict=""
    if [[ $ai_exit -eq 0 ]]; then
        verdict=$(grep -oE '^(KEEP|STALE):.*$' "$ai_out" | head -1 || true)
    fi
    rm -f "$ai_out"

    # En cas d'absence de verdict clair, on conserve par défaut (safe)
    if [[ -z "$verdict" ]]; then
        verdict="KEEP: verdict IA absent ou illisible (conservation par sécurité)"
    fi

    echo "$verdict"
}

main_rebase() {
    header "AI Pipeline - Mode REBASE / Cleanup PRs"
    log "Log: $LOG_FILE"

    check_prerequisites_light
    cd "$PROJECT_ROOT"

    # On part toujours de main propre pour ne pas polluer une branche en cours
    git checkout "$BASE_BRANCH" 2>/dev/null || true
    git pull "$REPO_REMOTE" "$BASE_BRANCH" 2>/dev/null || true

    local prs_json
    prs_json=$(_rebase_list_pipeline_prs)

    local pr_count
    pr_count=$(echo "$prs_json" | jq 'length' 2>/dev/null || echo 0)

    if [[ "$pr_count" -eq 0 || "$pr_count" == "null" ]]; then
        ok "Aucune PR pipeline ouverte - rien à faire"
        return 0
    fi

    log "${pr_count} PR(s) pipeline ouverte(s) à examiner"

    local rebased=0 closed=0 kept=0 failed=0

    # tsv pour parsing simple (les champs peuvent contenir des newlines → jq @tsv
    # remplace par \t \n littéraux, qu'on re-substitue ensuite)
    while IFS=$'\t' read -r pr_num branch title body mergeable url; do
        [[ -z "$pr_num" ]] && continue

        # jq @tsv encode les sauts de ligne en littéral \n — on les restaure
        body=${body//\\n/$'\n'}
        title=${title//\\n/ }

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

        if [[ "$mergeable" == "CONFLICTING" ]]; then
            if ! check_ai_tokens; then
                err "Agent IA indisponible - arrêt du rebase"
                return 1
            fi
            if _rebase_rebase_pr "$pr_num" "$branch"; then
                rebased=$((rebased + 1))
            else
                failed=$((failed + 1))
            fi
            continue
        fi

        # Cas MERGEABLE / UNKNOWN : check de pertinence
        if ! check_ai_tokens; then
            err "Agent IA indisponible - arrêt du rebase"
            return 1
        fi

        local verdict
        verdict=$(_rebase_check_pr_relevance "$pr_num" "$title" "$body")
        log "    Verdict: $verdict"

        if [[ "$verdict" == STALE:* ]]; then
            local reason="${verdict#STALE: }"
            warn "Fermeture PR #${pr_num} : ${reason}"

            gh pr close "$pr_num" --delete-branch \
                --comment "Fermée automatiquement par AI Pipeline — PR plus pertinente : ${reason}" \
                2>&1 | tee -a "$LOG_FILE" || true

            # Fermer aussi les issues liées
            local issue_refs
            issue_refs=$(_rebase_extract_closing_issues "$body")
            local n
            for n in $issue_refs; do
                gh issue close "$n" \
                    --comment "Fermée automatiquement par AI Pipeline (PR #${pr_num} obsolète) — ${reason}" \
                    2>&1 | tee -a "$LOG_FILE" || true
                ok "Issue #${n} fermée"
            done

            closed=$((closed + 1))
        else
            kept=$((kept + 1))
        fi
    done < <(echo "$prs_json" | jq -r '.[] | [.number, .headRefName, .title, .body, .mergeable, .url] | @tsv')

    header "Mode rebase terminé"
    log "  Rebasées : $rebased"
    log "  Fermées  : $closed"
    log "  Conservées : $kept"
    log "  Échecs   : $failed"
}
