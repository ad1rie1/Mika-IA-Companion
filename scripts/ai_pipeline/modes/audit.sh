#!/usr/bin/env bash
# ============================================================================
# AI Pipeline - Mode AUDIT (analyse en profondeur, crée des issues GitHub)
# ============================================================================

build_audit_prompt() {
    local module_paths="$1"
    local existing_issues="$2"

    # Un profil de proposition (features) ne constate pas des « problèmes » : le
    # gabarit de sortie est le même, le vocabulaire ne peut pas l'être, sinon on
    # demande des idées de fonctionnalités dans un formulaire de rapport de bug.
    local objet="problème" objets="problèmes" verbe="signale"
    local severity_line="severity: critical|high|medium|low"
    local body_hint="- Où se situe le problème (fichier, fonction, ligne approximative)
- Le scénario concret : entrée ou situation → conséquence observable
- Quel est le risque ou l'impact
- Une suggestion de correction"
    if audit_profile_is_proposal "$PROFILE"; then
        objet="proposition"; objets="propositions"; verbe="propose"
        severity_line="severity: high|medium|low   (= impact attendu, jamais critical)"
        body_hint="- Le constat, avec les fichiers concernés
- La proposition, du point de vue de l'usage
- Pourquoi ça a du sens pour ce projet
- L'esquisse d'implémentation (fichiers, couture empruntée, événements et upcasters, impact prompt/protocole)
- Le coût : petit / moyen / gros
- Ce que ce n'est pas"
        if [[ "$PROFILE" == "amelioration" ]]; then
            body_hint="- L'axe : plus humaine, ou plus fonctionnelle
- Le constat, avec les fichiers concernés
- Le scénario : situation → ce qu'elle fait (ou ce que vit l'utilisateur) → ce qu'une personne ferait (ou ce dont il aurait besoin)
- L'amélioration proposée
- La cible d'intention qui la validera, avec le contre-exemple qui doit échouer
- L'esquisse d'implémentation (faculté, événements, faits, sections, upcasters, clients touchés)
- Le coût : petit / moyen / gros
- Ce que ce n'est pas"
        fi
    fi

    # Seuil de gravité : seulement pour les profils qui signalent des défauts.
    local threshold_section=""
    if ! audit_profile_is_proposal "$PROFILE"; then
        threshold_section="## Seuil de gravité de ce passage : ${AUDIT_SEVERITE_MIN} et plus

Ne retiens que les ${objets} de gravité \`${AUDIT_SEVERITE_MIN}\` ou plus ($(severities_from "$AUDIT_SEVERITE_MIN")). Évalue la gravité honnêtement : un constat sous le seuil ne sera pas créé.
"
    fi

    local existing_section=""
    if [[ -n "$existing_issues" ]]; then
        existing_section="## Issues DÉJÀ connues pour ce module (NE PAS ${verbe}r à nouveau)

Tous profils confondus (bugs, qualité, sécurité, idées), ouvertes et fermées depuis ${DEDUP_CLOSED_DAYS:-90} jours. Ne les reprends PAS, même reformulées, même vues sous un autre angle : un défaut déjà signalé en qualité est le même défaut en bug. Une issue fermée a été traitée : ne la re-signale que si tu as vérifié dans le code que le défaut est toujours là, et dis-le dans la description en citant son numéro.

${existing_issues}
"
    fi

    cat <<PROMPT
${PROFILE_CONTENT}

$(ai_project_context)

## Mode : AUDIT UNIQUEMENT

Tu es en mode audit. Tu ne dois PAS modifier de fichiers.
Tu dois UNIQUEMENT analyser le code et lister les ${objets} que tu retiens.

## Périmètre d'analyse

Concentre ton analyse sur les modules suivants : ${module_paths}
Tu peux lire n'importe quel fichier du projet si nécessaire (contrats, faits, événements des autres facultés, frontend…).
$(module_scope_note "$module_paths")

${existing_section}
${threshold_section}
## Contraintes ABSOLUES

1. Tu peux UNIQUEMENT LIRE des fichiers - NE MODIFIE AUCUN FICHIER
2. Tu ne dois exécuter AUCUNE commande git
3. Tu ne dois exécuter AUCUNE commande système destructive
4. Tu ne dois exécuter AUCUN test (voir la politique de tests ci-dessous)

$(ai_test_policy read)

## Format de sortie OBLIGATOIRE

Pour chaque ${objet}, utilise EXACTEMENT ce format (un bloc par ${objet}, marqueurs seuls sur leur ligne) :

ISSUE_START
title: Titre court et clair en français
${severity_line}
files: fichier1.py, fichier2.py
description:
Description détaillée en français.
Inclure :
${body_hint}
ISSUE_END

Termine OBLIGATOIREMENT par la liste des pistes que tu as examinées puis écartées (au plus 10, les plus sérieuses), pour qu'un humain puisse juger de la profondeur de l'analyse — y compris, et surtout, si tu ne retiens rien :

ECARTES_START
- fichier:fonction — ce que tu as soupçonné — pourquoi tu l'as écarté (protégé ailleurs, choix délibéré d'un ADR, sous le seuil, scénario impossible…)
ECARTES_END

Si tu n'as rien à ${verbe}r sur ce module, n'émets aucun bloc ISSUE et dis-le en une phrase, avant la liste des pistes écartées.
Réponds TOUJOURS en français.
PROMPT
}

main_audit() {
    header "AI Pipeline - Mode AUDIT"
    log "Profil: ${PROFILE}"
    audit_profile_is_proposal "$PROFILE" || log "Seuil de gravité: ${AUDIT_SEVERITE_MIN} ($(severities_from "$AUDIT_SEVERITE_MIN"))"
    log "Modules: $MODULES"
    log "Log: $LOG_FILE"

    # 1. Prérequis
    check_prerequisites

    # 2. Résoudre les modules
    local module_paths
    if [[ "$MODULES" == "all" ]]; then
        local picked
        picked=$(pick_module audit "$PROFILE")
        if [[ -z "$picked" ]]; then
            ok "Tous les modules ont déjà des issues '${PROFILE}' ouvertes. Rien à faire."
            exit "$EXIT_NOTHING"
        fi
        MODULES="$picked"
        log "Module choisi automatiquement: $picked"
        module_paths="$picked"
    else
        module_paths=$(resolve_modules "$MODULES") || exit "$EXIT_FAIL"
    fi
    report_set module "$module_paths"
    log "Module ciblé: $module_paths"

    # 3. Récupérer les issues connues pour éviter les doublons. Une requête
    #    en échec ne vaut pas « aucune issue » : l'audit recréerait tout.
    local existing_issues
    if ! existing_issues=$(get_known_issues "$module_paths"); then
        err "Impossible de lister les issues existantes - audit annulé pour ne pas créer de doublons"
        exit "$EXIT_FAIL"
    fi
    if [[ -n "$existing_issues" ]]; then
        log "Issues connues pour ${module_paths} (tous profils):"
        local line
        while IFS= read -r line; do log "  $line"; done <<< "$existing_issues"
    else
        log "Aucune issue connue pour ce module"
    fi

    # 4. Construire et lancer le prompt IA (lecture seule)
    local prompt
    prompt=$(build_audit_prompt "$module_paths" "$existing_issues")

    if [[ "$DRY_RUN" == true ]]; then
        log "Prompt qui serait envoyé:"
        echo "$prompt"
        ok "Dry-run terminé"
        exit "$EXIT_OK"
    fi

    # L'agent lit l'état distant de la branche de base, pas la copie de travail
    # de l'utilisateur (et ses modifications en cours).
    ensure_workspace || exit "$EXIT_FAIL"

    header "Lancement de l'audit IA"
    local ai_exit=0 ai_out ai_output
    # Background + wait : permet au trap Ctrl+C de s'exécuter sans attendre la fin de l'agent IA
    ai_out=$(mktemp)
    run_ai_agent "read" "$prompt" "$ai_out" &
    wait $! || ai_exit=$?
    ai_output=$(cat "$ai_out")
    rm -f "$ai_out"

    echo "$ai_output" >> "$LOG_FILE"

    if [[ $ai_exit -ne 0 ]]; then
        err "$(ai_agent_label) a échoué (exit: $ai_exit, timeout: $(ai_agent_timeout)s)"
        echo "$ai_output" | tail -10
        notify "failure" "Audit ${PROFILE} échoué - $(ai_agent_label) exit $ai_exit"
        exit "$EXIT_FAIL"
    fi

    ok "Audit IA terminé"

    # Les pistes écartées : sans elles, un audit vide ne se distingue pas d'un
    # audit qui n'a pas cherché.
    local discarded
    discarded=$(sed -n '/ECARTES_START/,/ECARTES_END/p' <<< "$ai_output" | grep -v 'ECARTES_START\|ECARTES_END' || true)
    if [[ -n "$discarded" ]]; then
        log "Pistes examinées puis écartées par l'agent :"
        while IFS= read -r line; do
            [[ -n "${line// /}" ]] && log "  ${line}"
        done <<< "$discarded"
    else
        warn "L'agent n'a listé aucune piste écartée"
    fi

    # 5. Parser les issues trouvées
    local issues_dir issue_count
    issues_dir=$(parse_audit_issues "$ai_output")
    issue_count=$(find "${issues_dir}" -maxdepth 1 -name 'issue_*.txt' 2>/dev/null | wc -l)

    if [[ "$issue_count" -eq 0 ]]; then
        ok "Aucun problème détecté par l'audit"
        rm -rf "$issues_dir"
        notify "success" "Audit ${PROFILE} sur ${module_paths} - Aucun problème"
        exit "$EXIT_NO_RESULT"
    fi

    log "${issue_count} constat(s) retenu(s)"

    # 6. Toutes les issues du dépôt, pour le filet anti-doublons
    local pool
    pool=$(mktemp)
    if ! fetch_dedup_pool "$pool"; then
        rm -f "$pool"
        if [[ "$NO_CREATE" != true ]]; then
            err "Impossible de lister les issues du dépôt - création annulée pour ne pas créer de doublons"
            rm -rf "$issues_dir"
            exit "$EXIT_FAIL"
        fi
        warn "Issues du dépôt illisibles - aperçu sans contrôle des doublons"
        pool=""
    fi

    if [[ "$NO_CREATE" == true ]]; then
        warn "Création d'issues désactivée (--no-create)"
        log "Constats :"
        local f verdict number score other sev
        for f in "${issues_dir}"/issue_*.txt; do
            echo "---" | tee -a "$LOG_FILE"
            sev=$(_issue_field "$f" severity | awk '{print tolower($1)}')
            if ! audit_profile_is_proposal "$PROFILE" \
                && (( $(severity_rank "$sev") > 0 && $(severity_rank "$sev") < $(severity_rank "$AUDIT_SEVERITE_MIN") )); then
                log "→ sous le seuil (${sev} < ${AUDIT_SEVERITE_MIN}) : ne serait PAS créée"
            elif [[ -n "$pool" ]]; then
                IFS=$'\t' read -r verdict number score other \
                    < <(dedup_check "$pool" "$(_issue_field "$f" title)" "$(_issue_field "$f" files)" || echo "new")
                case "$verdict" in
                    skip)   warn "→ doublon de #${number} (${score}) : ne serait PAS créée — ${other}" ;;
                    flag)   warn "→ doublon possible de #${number} (${score}) : créée sans Propose_AI_PR — ${other}" ;;
                    closed) log  "→ proche de l'issue fermée #${number} (${score}) : créée avec un renvoi — ${other}" ;;
                esac
            fi
            tee -a "$LOG_FILE" < "$f"
        done
        rm -rf "$issues_dir"
        rm -f "$pool"
        exit "$EXIT_OK"
    fi

    header "Création des issues GitHub"
    local counts created skipped flagged below
    counts=$(create_github_issues "$issues_dir" "$PROFILE" "$module_paths" "$pool")
    rm -f "$pool"
    read -r created skipped flagged below <<< "$counts"
    report_set issues "$created"
    report_set doublons "$skipped"
    report_set a_trancher "$flagged"
    report_set sous_le_seuil "$below"

    if [[ "$created" -eq 0 && $(( skipped + below )) -gt 0 ]]; then
        ok "${issue_count} constat(s), rien de nouveau (${skipped} doublon(s), ${below} sous le seuil ${AUDIT_SEVERITE_MIN})"
        notify "success" "Audit ${PROFILE} sur ${module_paths} - rien de nouveau (${skipped} doublon(s), ${below} sous le seuil)"
        exit "$EXIT_NO_RESULT"
    fi
    if [[ "$created" -eq 0 ]]; then
        err "${issue_count} constat(s), mais aucune issue n'a pu être créée"
        notify "failure" "Audit ${PROFILE} sur ${module_paths} - création des issues en échec"
        exit "$EXIT_FAIL"
    fi

    # 7. Notifications
    notify "success" "Audit ${PROFILE} sur ${module_paths} - ${created} issue(s) créée(s), ${skipped} doublon(s) écarté(s), ${flagged} à trancher"

    header "Audit terminé avec succès"
    log "Module: $module_paths"
    log "Issues créées: $created (dont ${flagged} doublon(s) possible(s), sans Propose_AI_PR)"
    log "Doublons écartés: $skipped"
    log "Sous le seuil ${AUDIT_SEVERITE_MIN}: $below"
    log "Log complet: $LOG_FILE"
    exit "$EXIT_OK"
}
