#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Fonctions GitHub (PR, issues, labels, déduplication)
# ============================================================================
#
# Convention de sortie : une fonction appelée dans `$(...)` n'écrit QUE son
# résultat sur stdout, tout message va sur stderr. `create_pull_request`
# imprimait sa bannière sur stdout : l'« URL » de la PR transmise aux
# notifications contenait trois lignes de décor.

# Crée un label GitHub s'il n'existe pas (silencieux : il est appelé dans des
# fonctions dont la sortie est capturée). Un label déjà assuré dans ce
# processus ne coûte plus d'appel.
declare -A _ENSURED_LABELS=()
ensure_label() {
    local name="$1"
    local color="${2:-bfdadc}"
    local desc="${3:-}"
    [[ -n "${_ENSURED_LABELS[$name]:-}" ]] && return 0
    gh label create "$name" --color "$color" --description "$desc" >/dev/null 2>&1 || true
    _ENSURED_LABELS[$name]=1
}

# Labels de module et de groupe d'une issue.
ensure_module_labels() {
    local module="$1" group="$2"
    [[ -n "$module" ]] && ensure_label "$(module_label "$module")" "bfdadc" "Module ${module}"
    [[ -n "$group" ]] && ensure_label "groupe:${group}" "5319e7" "${MODULE_GROUP_DESCRIPTIONS[$group]:-Groupe ${group}}"
    return 0
}

ai_agent_pr_label() {
    echo "ai-agent:${AI_AGENT}"
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

# -- PR ouvertes du pipeline --------------------------------------------------

# PR ouvertes dont la branche commence par <préfixe>, une par ligne :
#   numéro|branche|url
# Filtrées par jq sur le nom de branche, et non par `--search head:…` : l'API
# Search ne suit pas les renommages de dépôt (cf. gh_query), et son `head:`
# matche un mot, pas un préfixe exact.
open_prs_with_branch_prefix() {
    local prefix="$1"
    gh_query gh pr list --state open --limit 1000 \
        --json number,headRefName,url \
        --jq ".[] | select(.headRefName | startswith(\"${prefix}\")) | \"\(.number)|\(.headRefName)|\(.url)\""
}

# Vérifie s'il existe déjà une PR ouverte pour une issue donnée. Le motif
# `issue-<n>-` est délimité : `issue-4` matchait aussi `issue-42`.
# Une requête en échec compte comme « PR existante » : sauter une issue se
# rattrape au tour suivant, une PR en double non.
check_existing_issue_pr() {
    local issue="$1"
    local match
    if ! match=$(open_prs_with_branch_prefix "${BRANCH_PREFIX}/issue-${issue}-"); then
        warn "Vérification des PR existantes impossible pour l'issue #${issue} - abandon par précaution" >&2
        return 0
    fi
    if [[ -n "$match" ]]; then
        warn "PR déjà ouverte pour l'issue #${issue}: $(head -1 <<< "$match" | cut -d'|' -f3)" >&2
        return 0
    fi
    return 1
}

# -- Choix d'un module --------------------------------------------------------

# Retourne 0 si le (profil, module) est déjà couvert : une PR ouverte (mode
# fix) ou une issue d'audit ouverte (mode audit). Une requête en échec renvoyait
# autrefois « 0 », c'est-à-dire « pas couvert » : le pipeline repartait
# travailler sur un module déjà traité et ouvrait un doublon. En cas d'échec on
# considère le module comme couvert — le sauter se rattrape au tour suivant.
_module_is_covered() {
    local kind="$1" profile="$2" mod="$3"
    local count
    local -a query=(gh pr list --state open --limit 1 --label "$PR_LABEL")
    [[ "$kind" == "audit" ]] && query=(gh issue list --state open --limit 1 --label "ai-audit")
    if ! count=$(gh_query "${query[@]}" \
        --label "ai-${profile}" \
        --label "$(module_label "$mod")" \
        --json number --jq 'length'); then
        warn "Dédup impossible pour ${profile}/${mod} - module sauté par précaution" >&2
        return 0
    fi
    [[ "$count" -gt 0 ]]
}

# Choisit au hasard un module non couvert pour ce profil.
#   pick_module pr|audit <profil>
# Les modules déjà vus dans la session run.sh courante arrivent en CSV par
# AI_PIPELINE_SKIP_MODULES.
pick_module() {
    local kind="$1" profile="$2"

    local -a session_skip=()
    if [[ -n "${AI_PIPELINE_SKIP_MODULES:-}" ]]; then
        IFS=',' read -ra session_skip <<< "$AI_PIPELINE_SKIP_MODULES"
    fi

    local -a available=()
    local mod skipped is_skipped
    for mod in "${AVAILABLE_MODULES[@]}"; do
        module_in_base "$mod" || continue

        # GitHub refuse un label de plus de 50 caractères, et ensure_label
        # échoue en silence : toutes les issues du module partaient en erreur.
        local label
        label=$(module_label "$mod")
        if (( ${#label} > 50 )); then
            warn "Module ignoré, label trop long pour GitHub (> 50) : ${label} - l'abréger dans MODULE_LABEL_PREFIXES" >&2
            continue
        fi

        is_skipped=false
        for skipped in "${session_skip[@]}"; do
            if [[ -n "$skipped" && "$skipped" == "$mod" ]]; then
                is_skipped=true
                break
            fi
        done
        [[ "$is_skipped" == true ]] && continue

        _module_is_covered "$kind" "$profile" "$mod" && continue
        available+=("$mod")
    done

    [[ ${#available[@]} -eq 0 ]] && return 0
    echo "${available[RANDOM % ${#available[@]}]}"
}

# Issues d'audit déjà connues pour un module ou un groupe (son label :
# `module:…` ou `groupe:…`), montrées à l'agent pour qu'il ne les reprenne
# pas : TOUS profils (un même défaut revenait en bugs, puis en quality ou
# security), ouvertes et fermées depuis DEDUP_CLOSED_DAYS jours.
# Une ligne par issue : « #n [profil] ouverte|fermée le AAAA-MM-JJ - titre ».
get_known_issues() {
    local label="$1" json
    json=$(gh_query gh issue list --state all --limit 1000 \
        --label "ai-audit" \
        --label "$label" \
        --json number,title,state,closedAt,labels) || return 1
    jq -r --argjson days "${DEDUP_CLOSED_DAYS:-90}" '
        (now - $days * 86400) as $since
        | .[]
        | select(.state == "OPEN"
                 or ((.closedAt // "1970-01-01T00:00:00Z") | fromdateiso8601) > $since)
        | ([.labels[].name | select(IN("ai-bugs", "ai-quality", "ai-security", "ai-features"))][0]
           // "?" | sub("^ai-"; "")) as $profile
        | "#\(.number) [\($profile)] "
          + (if .state == "OPEN" then "ouverte" else "fermée le \(.closedAt[0:10])" end)
          + " - \(.title)"
    ' <<< "$json"
}

# Toutes les issues du dépôt (ouvertes et fermées), pour le filet anti-doublons.
#   fetch_dedup_pool <fichier>
fetch_dedup_pool() {
    local out="$1" json
    json=$(gh_query gh issue list --state all --limit 1000 --json number,title,state,body) || return 1
    printf '%s' "$json" > "$out"
}

# Verdict du filet anti-doublons pour une issue à créer (cf. lib/dedup.py) :
# une ligne TSV « verdict numéro score titre ».
dedup_check() {
    local pool="$1" title="$2" files="$3"
    python3 "${_CONFIG_DIR}/lib/dedup.py" "$pool" --title "$title" --files "$files" \
        --skip "${DEDUP_SKIP:-0.8}" --flag "${DEDUP_FLAG:-0.6}"
}

# -- Création PR --------------------------------------------------------------

# Ouvre la PR d'une branche déjà poussée et écrit son URL sur stdout, rien
# d'autre.
create_pull_request() {
    local branch_name="$1"
    local base_ref="$2"

    header "Création de la Pull Request" >&2

    local commit_log changed_files
    commit_log=$(git log --oneline "${base_ref}..HEAD")
    changed_files=$(git diff --stat "${base_ref}..HEAD")

    local corrections_list="" line
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        corrections_list+="- \`${line}\`"$'\n'
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

    # PR_LABEL doit exister AVANT le `gh pr create` : un label inconnu fait
    # échouer la création entière.
    ensure_label "$PR_LABEL" "0e8a16" "PR proposée par AI Pipeline"
    local -a extra_args=(--label "$PR_LABEL" --label "$(ensure_ai_agent_pr_label)")

    if [[ -n "$PROFILE" ]]; then
        ensure_label "ai-${PROFILE}" "d73a4a" "AI Pipeline - ${PROFILE}"
        extra_args+=(--label "ai-${PROFILE}")
    fi
    if [[ -n "$MODULES" && "$MODULES" != "all" && "$MODULES" != *" "* ]]; then
        ensure_label "$(module_label "$MODULES")" "bfdadc" "Module ${MODULES}"
        extra_args+=(--label "$(module_label "$MODULES")")
        local group
        group=$(module_group "$MODULES")
        if [[ -n "$group" ]]; then
            ensure_label "groupe:${group}" "5319e7" "${MODULE_GROUP_DESCRIPTIONS[$group]:-Groupe ${group}}"
            extra_args+=(--label "groupe:${group}")
        fi
    fi
    [[ "$PR_DRAFT" == true ]] && extra_args+=(--draft)
    [[ -n "$PR_REVIEWERS" ]] && extra_args+=(--reviewer "$PR_REVIEWERS")

    local pr_url
    pr_url=$(gh pr create \
        --base "$BASE_BRANCH" \
        --head "$branch_name" \
        --title "$pr_title" \
        --body "$pr_body" \
        "${extra_args[@]}" \
        2>&1) || {
        err "Échec création PR: $pr_url" >&2
        return 1
    }

    pr_url=$(tail -n 1 <<< "$pr_url")
    ok "PR créée: $pr_url" >&2
    echo "$pr_url"
}

# -- Création issues ----------------------------------------------------------

# Découpe la sortie d'audit en un fichier par bloc ISSUE_START…ISSUE_END.
# Les marqueurs sont reconnus même indentés ou suivis d'espaces / d'un \r.
parse_audit_issues() {
    local agent_output="$1"
    local tmpdir
    tmpdir=$(mktemp -d)

    local in_issue=false issue_idx=0 current_file="" line marker
    while IFS= read -r line; do
        line="${line%$'\r'}"
        marker="${line//[[:space:]]/}"
        if [[ "$marker" == "ISSUE_START" ]]; then
            in_issue=true
            issue_idx=$((issue_idx + 1))
            current_file="${tmpdir}/issue_${issue_idx}.txt"
            : > "$current_file"
            continue
        fi
        if [[ "$marker" == "ISSUE_END" ]]; then
            in_issue=false
            continue
        fi
        if [[ "$in_issue" == true && -n "$current_file" ]]; then
            printf '%s\n' "$line" >> "$current_file"
        fi
    done <<< "$agent_output"

    echo "$tmpdir"
}

# Champ « clé: valeur » d'un bloc d'audit parsé.
_issue_field() {
    grep -m1 "^$2:" "$1" | sed "s/^$2: *//"
}

# Crée les issues GitHub d'un audit, en passant chacune au seuil de gravité
# (AUDIT_SEVERITE_MIN) puis au filet anti-doublons (lib/dedup.py) contre
# <pool>, la liste JSON des issues du dépôt. Écrit sur stdout
# « créées doublons_écartés doublons_signalés sous_le_seuil ».
#
# En passage par groupe, <module> est vide : chaque issue retrouve son module
# d'après ses fichiers (et garde ainsi un label de module précis), à défaut
# elle ne porte que le label du groupe.
#   create_github_issues <dossier> <profil> <module|""> <pool> [groupe]
create_github_issues() {
    local issues_dir="$1"
    local profile="$2"
    local module="$3"
    local pool="$4"
    local group="${5:-}"
    local created=0 skipped=0 flagged=0 below=0

    ensure_label "ai-audit" "1d76db" "Issue créée par AI Pipeline (audit)"
    ensure_label "ai-${profile}" "d73a4a" "Audit IA - ${profile}"
    [[ -n "$module" ]] && group=$(module_group "$module")

    # Propose_AI_PR déclenche la reprise automatique par le worker. Certains
    # profils ne doivent pas l'obtenir : une idée de fonctionnalité se décide
    # avant d'être codée. Le label s'ajoute alors à la main sur l'issue retenue.
    local auto_pr=true
    audit_profile_is_proposal "$profile" && auto_pr=false
    if [[ "$auto_pr" == true ]]; then
        ensure_label "Propose_AI_PR" "5319e7" "Demande de PR automatique par IA"
    else
        ensure_label "idee" "c2e0c6" "Proposition à arbitrer avant implémentation"
        log "Profil '${profile}' : issues créées SANS Propose_AI_PR (arbitrage humain)" >&2
    fi

    local issue_file
    for issue_file in "${issues_dir}"/issue_*.txt; do
        [[ ! -f "$issue_file" ]] && continue

        local title severity files description
        title=$(_issue_field "$issue_file" title)
        # Premier mot seulement : « high (impact sur chaque tour) » doit donner high.
        severity=$(_issue_field "$issue_file" severity | awk '{print tolower($1)}')
        files=$(_issue_field "$issue_file" files)
        # Le texte peut commencer sur la ligne même de « description: ».
        description=$(sed -n '/^description:/,$ p' "$issue_file" | sed '1s/^description: *//' | sed '1{/^$/d}')

        if [[ -z "$title" ]]; then
            warn "Issue sans titre dans $issue_file, ignorée" >&2
            continue
        fi

        # Seuil de gravité, pour les profils qui signalent des défauts. Une
        # gravité illisible passe (elle deviendra « medium » plus bas).
        if [[ "$auto_pr" == true ]] \
            && (( $(severity_rank "$severity") > 0 \
                  && $(severity_rank "$severity") < $(severity_rank "$AUDIT_SEVERITE_MIN") )); then
            log "Sous le seuil (${severity} < ${AUDIT_SEVERITE_MIN}) - non créée : ${title}" >&2
            below=$((below + 1))
            continue
        fi

        # Filet anti-doublons. Un doublon d'une issue ouverte n'est pas créé ;
        # un doublon possible l'est, mais sans Propose_AI_PR : le worker
        # n'y touche pas tant qu'un humain n'a pas tranché.
        local d_verdict="new" d_number="" d_score="" d_title="" dup_note=""
        if [[ -n "$pool" ]]; then
            IFS=$'\t' read -r d_verdict d_number d_score d_title \
                < <(dedup_check "$pool" "$title" "$files" || echo "new")
        fi
        case "$d_verdict" in
            skip)
                warn "Doublon de #${d_number} (titres semblables à ${d_score}) - non créée : ${title}" >&2
                skipped=$((skipped + 1))
                continue
                ;;
            flag)
                ensure_label "doublon-possible" "fef2c0" "Peut-être déjà signalé : à trancher avant correction"
                dup_note="> **Doublon possible de #${d_number}** (« ${d_title} » : titres semblables à ${d_score}, un fichier en commun). Si c'en est un, ferme celle-ci ; sinon retire \`doublon-possible\` et ajoute \`Propose_AI_PR\` pour la faire corriger."
                warn "Doublon possible de #${d_number} (${d_score}) - créée sans Propose_AI_PR : ${title}" >&2
                flagged=$((flagged + 1))
                ;;
            closed)
                dup_note="> Déjà signalé dans #${d_number}, aujourd'hui fermée (« ${d_title} ») : régression, ou correction incomplète ?"
                log "Proche de l'issue fermée #${d_number} (${d_score}) - créée avec un renvoi : ${title}" >&2
                ;;
        esac

        case "$severity" in
            critical|high|medium|low) ;;
            *) severity="medium" ;;
        esac

        local issue_module="$module" issue_group="$group"
        if [[ -z "$issue_module" ]]; then
            issue_module=$(module_for_files "$files")
            [[ -n "$issue_module" ]] && issue_group=$(module_group "$issue_module")
            issue_group="${issue_group:-$group}"
        fi
        ensure_module_labels "$issue_module" "$issue_group"
        local severity_label="severity:${severity}"
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
${dup_note:+
${dup_note}
}
**Profil d'analyse** : \`${profile}\`
**Module** : \`${issue_module:-groupe ${issue_group}}\`
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
            --label "${severity_label}"
        )
        [[ -n "$issue_module" ]] && issue_labels+=(--label "$(module_label "$issue_module")")
        [[ -n "$issue_group" ]] && issue_labels+=(--label "groupe:${issue_group}")
        if [[ "$d_verdict" == "flag" ]]; then
            issue_labels+=(--label "doublon-possible")
            [[ "$auto_pr" == true ]] || issue_labels+=(--label "idee")
        elif [[ "$auto_pr" == true ]]; then
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

        issue_url=$(tail -n 1 <<< "$issue_url")
        ok "Issue créée: ${issue_url}" >&2
        created=$((created + 1))

        # Une issue créée rejoint le pool : deux constats jumeaux du même
        # audit ne passent pas tous les deux.
        if [[ -n "$pool" ]]; then
            local number="${issue_url##*/}"
            [[ "$number" =~ ^[0-9]+$ ]] || number=0
            jq --argjson n "$number" --arg t "[AI][${profile}] ${title}" --arg b "$issue_body" \
                '. + [{number: $n, title: $t, state: "OPEN", body: $b}]' "$pool" > "${pool}.tmp" \
                && mv "${pool}.tmp" "$pool"
        fi
    done

    rm -rf "$issues_dir"
    echo "$created $skipped $flagged $below"
}
