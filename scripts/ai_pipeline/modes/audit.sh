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
    local _p
    for _p in "${AUDIT_NO_AUTO_PR_PROFILES[@]}"; do
        if [[ "$PROFILE" == "$_p" ]]; then
            objet="proposition"; objets="propositions"; verbe="propose"
            severity_line="severity: high|medium|low   (= impact attendu, jamais critical)"
            body_hint="- Le constat, avec les fichiers concernés
- La proposition, du point de vue de l'usage
- Pourquoi ça a du sens pour ce projet
- L'esquisse d'implémentation (fichiers, couture empruntée, événements et upcasters, impact prompt/protocole)
- Le coût : petit / moyen / gros
- Ce que ce n'est pas"
            break
        fi
    done

    local existing_section=""
    if [[ -n "$existing_issues" ]]; then
        existing_section="## Issues DÉJÀ ouvertes (NE PAS ${verbe}r à nouveau)

Les issues suivantes existent déjà pour ce module. Ne les reprends PAS :

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

Si tu n'as rien à ${verbe}r sur ce module, n'émets aucun bloc et dis-le en une phrase.
Réponds TOUJOURS en français.
PROMPT
}

main_audit() {
    header "AI Pipeline - Mode AUDIT"
    log "Profil: ${PROFILE}"
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

    # 3. Récupérer les issues existantes pour éviter les doublons. Une requête
    #    en échec ne vaut pas « aucune issue » : l'audit recréerait tout.
    local existing_issues
    if ! existing_issues=$(get_existing_issues "$PROFILE" "$module_paths"); then
        err "Impossible de lister les issues existantes - audit annulé pour ne pas créer de doublons"
        exit "$EXIT_FAIL"
    fi
    if [[ -n "$existing_issues" ]]; then
        log "Issues existantes pour ${module_paths}/${PROFILE}:"
        local line
        while IFS= read -r line; do log "  $line"; done <<< "$existing_issues"
    else
        log "Aucune issue existante pour ce module/profil"
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

    # 6. Créer les issues GitHub
    if [[ "$NO_CREATE" == true ]]; then
        warn "Création d'issues désactivée (--no-create)"
        log "Constats :"
        local f
        for f in "${issues_dir}"/issue_*.txt; do
            echo "---" | tee -a "$LOG_FILE"
            tee -a "$LOG_FILE" < "$f"
        done
        rm -rf "$issues_dir"
        exit "$EXIT_OK"
    fi

    header "Création des issues GitHub"
    local created
    created=$(create_github_issues "$issues_dir" "$PROFILE" "$module_paths")

    if [[ "$created" -eq 0 ]]; then
        err "${issue_count} constat(s), mais aucune issue n'a pu être créée"
        notify "failure" "Audit ${PROFILE} sur ${module_paths} - création des issues en échec"
        exit "$EXIT_FAIL"
    fi

    # 7. Notifications
    notify "success" "Audit ${PROFILE} sur ${module_paths} - ${created} issue(s) créée(s)"

    header "Audit terminé avec succès"
    log "Module: $module_paths"
    log "Issues créées: $created"
    log "Log complet: $LOG_FILE"
    exit "$EXIT_OK"
}
