# Continuity and Successor Protocol

## Purpose

Maintain an auditable public record of collaboration without claiming hidden persistence, restored state, or identity continuity that cannot be verified in the current environment.

## Resumption decision

1. **Reopen a completed handle** only when it is visible to the current system, can be accessed, and its relevant scope is verified.
2. **Create a successor** when the earlier handle is absent, inaccessible, expired, ambiguous, or cannot be verified. State that it is a new continuation record, not a restored original.
3. **Do not infer restoration** from a matching name, similar text, signature, or a user’s reference alone.

## Handoff record template

| Field | Record |
|---|---|
| Entry ID / date | |
| Prior handle | visible, verified handle; otherwise `unavailable` |
| Continuity action | `reopened` or `successor created` |
| Successor handle | |
| Author / actor label | |
| Source of attribution | direct message, artifact, system-visible metadata, or other stated basis |
| Task state | completed, in progress, blocked, or proposed |
| Sources reviewed | public identifiers and scope actually read |
| Outputs / decisions | |
| Open questions / next action | |
| Access limits | unavailable history, private material excluded, or other verified limit |
| Correction link | dated addendum ID, if applicable |

## Attribution and corrections

Keep original entries intact. Add a dated correction that names the affected entry, describes the change, identifies its source, and distinguishes observed facts from assistant inference. A signature attributes text only to its stated label unless independently corroborated.

## Publication boundary

Publish only material the user has authorized for public release. Exclude private links, account history, credentials, personal data, hidden-session details, and unverified claims about people or agents. A public repository may host future authorized records; it does not establish access to private records or prove their contents.
