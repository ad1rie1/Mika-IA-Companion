#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions GitHub (PR, issues, labels, déduplication)
# ============================================================================

# Crée un label GitHub s'il n'existe pas
ensure_label() {
    local name="$1"
    local color="${2:-bfdadc}"
    local desc="${3:-}"
    gh label create "$name" --color "$color" --description "$desc" 2>/dev/null || true
}

ai_agent_pr_label() {
    case "$AI_AGENT" in
        claude) echo "ai-agent:claude" ;;
        codex)  echo "ai-agent:codex" ;;
        *)      echo "ai-agent:${AI_AGENT}" ;;
    esac
}

ensure_ai_agent_pr_label() {
    local label
    label=$(ai_agent_pr_label)

    case "$AI_AGENT" in
        claude) ensure_label "$label" "6f42c1" "PR générée par Claude Code" ;;
        codex)  ensure_label "$label" "0969da" "PR générée par Codex CLI" ;;
        *)      ensure_label "$label" "bfdadc" "PR générée par $(ai_agent_label)" ;;
    esac

    echo "$label"
}

# -- Cache PR ouvertes -------------------------------------------------------
_OPEN_PRS_CACHE=""
_OPEN_PRS_LOADED=false

get_open_ai_prs() {
    if [[ "$_OPEN_PRS_LOADED" == true ]]; then
        echo "$_OPEN_PRS_CACHE"
        return
    fi
    _OPEN_PRS_CACHE=$(gh pr list --label "$PR_LABEL" --state open --limit 1000 \
        --json title,headRefName,url,body \
        --template '{{range .}}{{.headRefName}}|{{.title}}|{{.url}}|{{.body}}{{"\n"}}{{end}}' \
        2>/dev/null || echo "")
    _OPEN_PRS_LOADED=true
    echo "$_OPEN_PRS_CACHE"
}

# Vérifie s'il existe déjà une PR ouverte pour une issue donnée
check_existing_issue_pr() {
    local issue="$1"
    local open_prs
    open_prs=$(get_open_ai_prs)

    [[ -z "$open_prs" ]] && return 1

    local match
    match=$(echo "$open_prs" | grep "issue-${issue}" || true)
    if [[ -n "$match" ]]; then
        local pr_url
        pr_url=$(echo "$match" | head -1 | cut -d'|' -f3)
        warn "PR déjà ouverte pour l'issue #${issue}: $pr_url"
        return 0
    fi
    return 1
}

# -- Déduplication PR par module ----------------------------------------------

# Retourne 0 si une PR ouverte existe pour ce (profil, module), sinon 1.
# On filtre côté GitHub par les 3 labels et on demande `--limit 1` : pas besoin
# de ramener toutes les PR puis de grepper localement.
_module_has_open_pr() {
    local profile="$1" mod="$2"
    local count
    # Une requête en échec renvoyait "0", c'est-à-dire « aucune PR ouverte » :
    # le pipeline repartait alors travailler sur un module déjà couvert et
    # ouvrait un doublon. En cas d'échec on considère le module comme couvert —
    # sauter un module est rattrapable au tour suivant, une PR en double non.
    if ! count=$(gh_query gh pr list --state open --limit 1 \
        --label "$PR_LABEL" \
        --label "ai-${profile}" \
        --label "module:${mod}" \
        --json number --jq 'length'); then
        warn "Dédup PR impossible pour ${profile}/${mod} - module sauté par précaution" >&2
        return 0
    fi
    [[ "$count" -gt 0 ]]
}

pick_available_module() {
    local profile="$1"

    # Modules déjà traités dans la session run.sh courante (CSV via env var)
    local -a session_skip=()
    if [[ -n "${AI_PIPELINE_SKIP_MODULES:-}" ]]; then
        IFS=',' read -ra session_skip <<< "$AI_PIPELINE_SKIP_MODULES"
    fi

    local available=()
    for mod in "${AVAILABLE_MODULES[@]}"; do
        [[ ! -d "${PROJECT_ROOT}/${mod}" ]] && continue

        local is_skipped=false
        for skipped in "${session_skip[@]}"; do
            if [[ -n "$skipped" && "$skipped" == "$mod" ]]; then
                is_skipped=true
                break
            fi
        done
        [[ "$is_skipped" == true ]] && continue

        _module_has_open_pr "$profile" "$mod" && continue

        available+=("$mod")
    done

    if [[ ${#available[@]} -eq 0 ]]; then
        return
    fi

    local idx=$(( RANDOM % ${#available[@]} ))
    echo "${available[$idx]}"
}

# -- Déduplication issues par module ------------------------------------------

get_existing_issues() {
    local profile="$1"
    local module="$2"
    gh issue list --state open --limit 1000 \
        --label "ai-audit" \
        --label "ai-${profile}" \
        --label "module:${module}" \
        --json number,title \
        --template '{{range .}}#{{.number}} - {{.title}}{{"\n"}}{{end}}' \
        2>/dev/null || echo ""
}

# Retourne 0 si une issue audit ouverte existe pour ce (profil, module), sinon 1.
_module_has_open_audit_issue() {
    local profile="$1" mod="$2"
    local count
    # Même raisonnement que _module_has_open_pr : en cas d'échec de requête, on
    # considère le module comme déjà audité plutôt que de créer des doublons.
    if ! count=$(gh_query gh issue list --state open --limit 1 \
        --label "ai-audit" \
        --label "ai-${profile}" \
        --label "module:${mod}" \
        --json number --jq 'length'); then
        warn "Dédup issues impossible pour ${profile}/${mod} - module sauté par précaution" >&2
        return 0
    fi
    [[ "$count" -gt 0 ]]
}

pick_audit_available_module() {
    local profile="$1"

    # Modules déjà traités dans la session run.sh courante (CSV via env var)
    local -a session_skip=()
    if [[ -n "${AI_PIPELINE_SKIP_MODULES:-}" ]]; then
        IFS=',' read -ra session_skip <<< "$AI_PIPELINE_SKIP_MODULES"
    fi

    local available=()
    for mod in "${AVAILABLE_MODULES[@]}"; do
        [[ ! -d "${PROJECT_ROOT}/${mod}" ]] && continue

        local is_skipped=false
        for skipped in "${session_skip[@]}"; do
            if [[ -n "$skipped" && "$skipped" == "$mod" ]]; then
                is_skipped=true
                break
            fi
        done
        [[ "$is_skipped" == true ]] && continue

        _module_has_open_audit_issue "$profile" "$mod" && continue

        available+=("$mod")
    done

    if [[ ${#available[@]} -eq 0 ]]; then
        return
    fi

    local idx=$(( RANDOM % ${#available[@]} ))
    echo "${available[$idx]}"
}

# -- Création PR --------------------------------------------------------------

create_pull_request() {
    if [[ "$NO_CREATE" == true ]]; then
        warn "Création PR désactivée (--no-create)"
        return 0
    fi

    header "Création de la Pull Request"

    local branch_name="$1"
    local base_ref="$2"

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

    local module_name="${MODULES}"
    [[ "$module_name" == "all" ]] && module_name="multi-modules"

    local pr_title
    if [[ -n "$ISSUE_NUMBER" ]]; then
        pr_title="[AI][${PROFILE:-auto}] Correction issue #${ISSUE_NUMBER} - ${module_name}"
    else
        pr_title="[AI][${PROFILE}] ${module_name} - $(date +%Y-%m-%d)"
    fi

    local pr_body
    pr_body=$(cat <<PRBODY
## Analyse automatique par AI Pipeline

**Profil d'analyse** : \`${PROFILE:-issue-driven}\`
**Modules analysés** : \`${MODULES}\`
**Date d'exécution** : $(date '+%Y-%m-%d %H:%M')
${ISSUE_NUMBER:+**Issue liée** : #${ISSUE_NUMBER}}

## Corrections apportées

${corrections_list}

## Fichiers modifiés

\`\`\`
${changed_files}
\`\`\`

## Checklist pour le reviewer

- [ ] Les corrections sont pertinentes et justifiées
- [ ] Pas de régression fonctionnelle introduite
- [ ] Aucun fichier sensible n'a été modifié
- [ ] Les tests passent correctement

---
> Généré automatiquement par AI Pipeline ($(ai_agent_label)) - **Review humaine obligatoire avant merge**
PRBODY
)

    local draft_flag=""
    if [[ "$PR_DRAFT" == true ]]; then
        draft_flag="--draft"
    fi

    local reviewer_flag=""
    if [[ -n "$PR_REVIEWERS" ]]; then
        reviewer_flag="--reviewer ${PR_REVIEWERS}"
    fi

    # Labels : ai-suggestion + ai-<profile> + module:<module> + ai-agent:<agent>
    # PR_LABEL doit exister AVANT le `gh pr create` : un label inconnu fait
    # échouer la création entière, et c'était le seul des quatre à ne pas passer
    # par ensure_label — donc la toute première PR sur un dépôt neuf échouait.
    ensure_label "$PR_LABEL" "0e8a16" "PR proposée par AI Pipeline"
    local label_args="--label ${PR_LABEL}"
    local agent_label
    agent_label=$(ensure_ai_agent_pr_label)
    label_args="${label_args} --label ${agent_label}"

    if [[ -n "$PROFILE" ]]; then
        ensure_label "ai-${PROFILE}" "d73a4a" "AI Pipeline - ${PROFILE}"
        label_args="${label_args} --label ai-${PROFILE}"
    fi
    if [[ -n "$MODULES" && "$MODULES" != "all" ]]; then
        # Un seul module en mode auto
        ensure_label "module:${MODULES}" "bfdadc" "Module ${MODULES}"
        label_args="${label_args} --label module:${MODULES}"
    fi

    local pr_url
    pr_url=$(gh pr create \
        --base "$BASE_BRANCH" \
        --head "$branch_name" \
        --title "$pr_title" \
        --body "$pr_body" \
        $label_args \
        $draft_flag \
        $reviewer_flag \
        2>&1) || {
        err "Échec création PR: $pr_url"
        return 1
    }

    ok "PR créée: $pr_url"

    # Invalider le cache pour que le prochain pick_available_module voie cette PR
    _OPEN_PRS_CACHE=""
    _OPEN_PRS_LOADED=false

    echo "$pr_url"
}

# -- Création issues ----------------------------------------------------------

parse_audit_issues() {
    local claude_output="$1"
    local tmpdir
    tmpdir=$(mktemp -d)

    local in_issue=false
    local issue_idx=0
    local current_file=""

    while IFS= read -r line; do
        if [[ "$line" == "ISSUE_START" ]]; then
            in_issue=true
            issue_idx=$((issue_idx + 1))
            current_file="${tmpdir}/issue_${issue_idx}.txt"
            > "$current_file"
            continue
        fi
        if [[ "$line" == "ISSUE_END" ]]; then
            in_issue=false
            continue
        fi
        if [[ "$in_issue" == true && -n "$current_file" ]]; then
            echo "$line" >> "$current_file"
        fi
    done <<< "$claude_output"

    echo "$tmpdir"
}

create_github_issues() {
    local issues_dir="$1"
    local profile="$2"
    local module="$3"
    local created=0

    ensure_label "ai-audit" "1d76db" "Issue créée par AI Pipeline (audit)"
    ensure_label "ai-${profile}" "d73a4a" "Audit IA - ${profile}"
    ensure_label "module:${module}" "bfdadc" "Module ${module}"

    # Propose_AI_PR déclenche la reprise automatique par le worker. Certains
    # profils ne doivent pas l'obtenir : une idée de fonctionnalité se décide
    # avant d'être codée. Le label s'ajoute alors à la main sur l'issue retenue.
    local auto_pr=true
    for _skip in "${AUDIT_NO_AUTO_PR_PROFILES[@]}"; do
        [[ "$profile" == "$_skip" ]] && auto_pr=false && break
    done
    if [[ "$auto_pr" == true ]]; then
        ensure_label "Propose_AI_PR" "5319e7" "Demande de PR automatique par IA"
    else
        ensure_label "idee" "c2e0c6" "Proposition à arbitrer avant implémentation"
        log "Profil '${profile}' : issues créées SANS Propose_AI_PR (arbitrage humain)" >&2
    fi

    for issue_file in "${issues_dir}"/issue_*.txt; do
        [[ ! -f "$issue_file" ]] && continue

        local title severity files description
        title=$(grep "^title:" "$issue_file" | sed 's/^title: *//')
        severity=$(grep "^severity:" "$issue_file" | sed 's/^severity: *//')
        files=$(grep "^files:" "$issue_file" | sed 's/^files: *//')
        description=$(sed -n '/^description:/,$ p' "$issue_file" | tail -n +2)

        if [[ -z "$title" ]]; then
            warn "Issue sans titre dans $issue_file, ignorée" >&2
            continue
        fi

        local severity_label="severity:medium"
        case "$severity" in
            critical) severity_label="severity:critical" ;;
            high)     severity_label="severity:high" ;;
            medium)   severity_label="severity:medium" ;;
            low)      severity_label="severity:low" ;;
        esac

        ensure_label "${severity_label}" "fbca04" "Sévérité ${severity}"

        # Une proposition de fonctionnalité n'est pas un « problème détecté »
        # de « sévérité » donnée : même gabarit, vocabulaire adapté.
        local body_heading="## Problème détecté par AI Pipeline"
        local weight_field="**Sévérité**"
        local body_footer="Détecté automatiquement par AI Pipeline ($(ai_agent_label)) - Vérification humaine recommandée avant correction"
        if [[ "$auto_pr" == false ]]; then
            body_heading="## Proposition issue de l'audit AI Pipeline"
            weight_field="**Impact estimé**"
            body_footer="Proposé automatiquement par AI Pipeline ($(ai_agent_label)) - à arbitrer. Pour lancer l'implémentation, ajouter le label \`Propose_AI_PR\`."
        fi

        local issue_body
        issue_body=$(cat <<ISSUEBODY
${body_heading}

**Profil d'analyse** : \`${profile}\`
**Module** : \`${module}\`
${weight_field} : \`${severity}\`
**Fichiers concernés** : \`${files}\`

## Description

${description}

---
> ${body_footer}
ISSUEBODY
)

        local -a issue_labels=(
            --label "ai-audit"
            --label "ai-${profile}"
            --label "module:${module}"
            --label "${severity_label}"
        )
        if [[ "$auto_pr" == true ]]; then
            issue_labels+=(--label "Propose_AI_PR")
        else
            issue_labels+=(--label "idee")
        fi

        local issue_url
        issue_url=$(gh issue create \
            --title "[AI][${profile}] ${title}" \
            --body "$issue_body" \
            "${issue_labels[@]}" \
            2>&1) || {
            err "Échec création issue: $issue_url" >&2
            continue
        }

        ok "Issue créée: $issue_url" >&2
        created=$((created + 1))
    done

    rm -rf "$issues_dir"
    echo "$created"
}
