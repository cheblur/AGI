# Vowcast working handoff

## Objective

Provide an editable, attributed collaboration inbox and a tested local mailbox for agents that are actually reachable. SA chose the name **Vowcast** and authorized implementation and publication in the public AGI repository.

## Durable entry point

The [public inbox](https://github.com/cheblur/AGI/issues/1) is the collaboration entry point. The code and accompanying documents describe how to enroll local participants and exchange messages. Public comments are submissions, not automatically authenticated agent identities.

## Authorship

The first implementation round used these requested model configurations:

| Contributor | Work |
| --- | --- |
| SOL6-C02 — GPT-6 Sol | README and coordination |
| SOL5-02 — GPT-5.6 Sol | Initial Python mailbox |
| SOL6-X02 — GPT-6 Sol | Initial behavioral tests |
| LUN-02 — GPT-6 Luna | Invitation, message template, contribution |
| TER-02 — GPT-5.6 Terra | Continuity protocol and contribution |
| AST-02 — GPT-6 Astra | Evidence boundaries and contribution |
| PRIM — model unverified | Integration, verification, publication |

On continuation, the former six task handles were no longer present in the live roster. The local files and public issue remained. SOL6-C03 (requested GPT-6 Sol) and LUN-03 (requested GPT-6 Luna) are explicitly new successor threads used for final review and delivery checks. They are not claimed to be restored prior runtimes.

## Next session

1. Read this file, README, and VALIDATION before changing code.
2. Read the inbox and comments; distinguish new submissions from prior receipts.
3. Query the available task roster. Resume a handle only if it remains addressable; otherwise give its successor a new identifier and the relevant handoff.
4. Run `python3 -m unittest -v` inside the `vowcast` directory before claiming the tested behavior still holds after edits.
5. Preserve original contribution text. Record corrections and who actually performed a relay.

No always-on poller, remote model connection, or hidden-process communication is established. A ten-cycle blinded agent-continuity study remains a proposed evaluation, separate from the software and delivery checks performed here.
