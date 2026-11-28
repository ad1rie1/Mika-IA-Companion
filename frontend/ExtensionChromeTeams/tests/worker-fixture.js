"use strict";
// Une commande d'envoi telle que la page Teams la passe à son worker (ADR 0301), de la forme relevée le 2026-11-22 :
// `autoSendMessage`, ses variables, sa file d'attente hors ligne. Partagée par `worker-send.test.js` et
// `capture.test.js` (ce fichier n'est pas un test : `npm test` ne lance que `*.test.js`).

const ALBERT = "19:3e51ce13-6eb8-463b-a75a-a40b2ab67602_7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab@unq.gbl.spaces";
const GROUP = "19:9f3c0b6e1d2a4c5b8e7f6a5b4c3d2e1f@thread.v2";
const CHANNEL = "19:Bd3f0c2a1b4e4d6f8a9c0b1d2e3f4a5b@thread.tacv2";
const MEETING = "19:meeting_NjQ5ZTFkNzMtYjYxZC00@thread.v2";
const TEXT = "essai 4 pour Albert";
const CLIENT_ID = "4123456789012345678";
const CORRELATION = "0f1e2d3c-4b5a-4968-8776-655443322110";
const RENDERER = "a1b2c3d4-renderer";
const WINDOW = "e5f6a7b8-window";
const QUERY = "mutation autoSendMessage($convId: ID!, $message: SendMessage!, $action: SendAction, "
  + "$offlineActionOptions: OfflineActionOptions) { autoSendMessage(convId: $convId, message: $message, "
  + "action: $action, offlineActionOptions: $offlineActionOptions) { id clientMessageId } }";

/** La commande (un objet : la page la passe en texte JSON), à changer par `over(command)`. */
function autoSend({ conv = ALBERT, content = "<p><semantic-object>" + TEXT + "</semantic-object></p>", request = 412,
  over } = {}) {
  const command = {
    requestId: "m-" + request,
    rendererId: RENDERER,
    windowId: WINDOW,
    payload: {
      graphqlQuery: QUERY,
      variables: {
        action: "Create",
        convId: conv,
        originalConvId: conv,
        correlationId: CORRELATION,
        isBilateralChat: conv.endsWith("@unq.gbl.spaces"),
        message: {
          clientMessageId: CLIENT_ID,
          content: content,
          messageType: "RichText/Html",
          importance: "Standard",
          sendPipelineThreadType: "Chats",
          originalSendPipelineTime: "1763812345678",
          computed: { mentions: [], plainText: content.replace(/<[^>]*>/g, "") },
          subject: null,
          files: null,
          quotedMessage: null,
          scheduledTime: null,
          senderDisplayName: "Adrien Martin",
        },
        offlineActionOptions: { actionId: "send_" + CLIENT_ID, actionType: "send", queueId: "sendMessage_" + conv,
          pendingUploadIds: [] },
        isUrgent: false,
        skipDraftCleanup: false,
      },
    },
    operationName: "autoSendMessage",
    type: "graphql",
    options: {},
  };
  if (over) over(command);
  return command;
}

/**
 * La commande d'envoi telle que Teams la passait vraiment le 2026-11-22 (relevée par la session principale dans le
 * tête-à-tête d'Albert, essai 6) : les mêmes clés, dans le même ordre, avec les mêmes types — les valeurs inventées.
 * La 0.8.0 l'écartait (« includeRepliesSummary » pris pour une réponse citée) : aucun modèle n'était jamais appris.
 */
function realSend({ conv = ALBERT, text = TEXT, request = 905 } = {}) {
  return {
    requestId: "m-" + request,
    rendererId: "5d0c7a4e-2b1f-4c3d-9e8a-7f6b5a4c3d2e",
    windowId: "main",
    payload: {
      graphqlQuery: QUERY,
      variables: {
        enableDiverseEmotionsNonreactive: false,
        includeRepliesSummary: true,
        includeRepliesSummaryNonreactive: false,
        deferAppMetaDataFragment: false,
        action: "Create",
        convId: conv,
        message: {
          content: "<p><semantic-object>" + text + "</semantic-object></p>",
          computed: { amsReferences: [], cards: [], embeddedLinks: [], isExpanded: false, offlineAssets: [],
            mentions: [], onBehalfOf: [], urlPreview: null, appIdsToInstall: [], blurHash: null },
          files: [], deeplinks: [], clientMessageId: CLIENT_ID, title: null, replyChainId: null,
          importance: "Standard", messageType: "RichText/Html", originalArrivalTime: null, policyViolation: null,
          subject: null, meeting: null, scheduledSendTime: null, targetedMsgRecipientId: null, forwardMessageIds: [],
          forwardMessageOriginalConvId: null, forwardedMessageContext: null, forwardMessageRecipients: [],
          forwardAppIdsToInstall: [], forwardMessageCardContents: null, forwardPrivateReply: false,
          forwardTeamId: null, isForwardedMessage: false, draftCreationTime: "1763812340000", postType: null,
          replyPermission: null, fluidUrlPermissionInfo: null, fluidProperties: null, crossPostChannels: [],
          crossPostId: null, sendPostAsEmail: null, shareToL1: null, sharedToMessageId: null, suggestedActions: null,
          from: null, originalSendPipelineTime: "1763812345678", overrideImDisplayNameT1: null, meetingChatType: null,
          sendPipelineThreadType: "Chats", isNewBotSession: false, inMeetingPrivateChatContext: null,
        },
        originalConvId: conv,
        correlationId: CORRELATION,
        searchSessionId: null,
        sendFromChannel_ToBeRefactored: false,
        offlineActionOptions: { queueId: "chats_" + conv, actionId: "send_" + CLIENT_ID, actionType: "send",
          pendingUploadIds: [] },
        isBilateralChat: false,
      },
    },
    operationName: "autoSendMessage",
    type: "graphql",
    cdlOperationCustomContext: {
      authenticationUser: { cloud: "prod", profile: { objectId: "3e51ce13-6eb8-463b-a75a-a40b2ab67602",
        tenantId: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", puid: "10032000ABCDEF12" },
      id: "3e51ce13-6eb8-463b-a75a-a40b2ab67602", isAuthenticated: true, role: "Member", type: "Aad",
      subType: "Default", loginUserName: "adrien.exemple@exemple.test",
      homeAccountId: "3e51ce13-6eb8-463b-a75a-a40b2ab67602", homeTenantId: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
      homeAccountCloud: "prod" },
    },
  };
}

/** Une requête quelconque de la page à son worker (son numéro fait avancer le compteur). */
function query(request, { renderer = RENDERER, window = WINDOW } = {}) {
  return { requestId: "q-" + request, rendererId: renderer, windowId: window,
    payload: { graphqlQuery: "query chatList { chats { id } }", variables: {} }, operationName: "chatList",
    type: "graphql", options: {} };
}

/** La réponse du worker à une requête. */
function reply(requestId, { status = "success", data = { autoSendMessage: { id: "1763900000123" } }, errors } = {}) {
  const response = { data: data, extensions: {} };
  if (errors) response.errors = errors;
  return { requestId: requestId, rendererId: RENDERER, windowId: WINDOW, type: "graphql", extensions: {},
    status: status, response: response };
}

module.exports = { ALBERT, GROUP, CHANNEL, MEETING, TEXT, CLIENT_ID, CORRELATION, RENDERER, WINDOW, autoSend, realSend,
  query, reply };
