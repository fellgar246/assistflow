# ADR 0015: A person and the assistant share one conversation

## Status

Accepted

## Context

When the assistant cannot finish a case, a person on the support team needs the same conversation: the transcript, why a change was proposed, and the pending confirmation. The customer should be able to tell a person from the automated assistant. Closing the case should close the linked ticket as well. A later message from the customer should not reopen a finished thread.

## Decision

Escalated conversations and conversations waiting for confirmation appear in a staff inbox, newest update first, and only for the staff member's tenant. The tenant and the agent id come from the verified access token. A customer token cannot open the inbox.

Take over records the agent on the conversation and on the linked ticket, and writes a system line that the person joined. A human reply is stored with the assistant role and author type `support_agent`, plus the person's display name. It is not a citation and it does not call a model. Resolve sets the conversation and the linked ticket to resolved. Repeating resolve does not append another close event.

A customer message sent to a resolved conversation opens a new conversation. The resolved thread stays as it was. The response header `X-Conversation-Id` names the conversation that received the message.

Staff confirmation runs the same approval command as the customer path. The stored arguments and arguments hash are checked again. The staff agent id is stored as `approved_by`.

The trace a person can read lists step kind, tool name, status, latency, and an error code when a tool failed or was blocked. Provider payloads, prompts, and raw arguments are not part of that response.

## Consequences

- The customer thread and the console show the same lifecycle: escalation, a human reply, confirmation, and resolve.
- A resolved case cannot grow new customer messages. A new question starts a new conversation.
- Local development signs in through the local issuer. The inbox commands do not read a tenant from the request.
