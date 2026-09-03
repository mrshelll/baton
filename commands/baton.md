---
description: Write this session's context handoff — a size-capped document, ready for the next session to pick up without losing the thread.
argument-hint: "[memory|continue] [optional short note]"
allowed-tools: Bash, Read, Write, Glob, Grep
---

Write this session's handoff following **exactly** the procedure in the `baton`
skill (`skills/baton/SKILL.md` in this plugin). Do not improvise a format of your
own: the code composes and validates the document, not you.

Arguments received: $ARGUMENTS

If the arguments start with `memory` or `continue`, that is the mode and you do
not have to decide it. Any remaining text is a note from the user about what they
want captured.
