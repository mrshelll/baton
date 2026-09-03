---
description: Write this session's context handoff — a size-capped document, ready for the next session to pick up without losing the thread.
argument-hint: "[memory|continue] [project] [optional short note]"
allowed-tools: Bash, Read, Write, Glob, Grep
---

Write this session's handoff following **exactly** the procedure in the `baton`
skill (`skills/baton/SKILL.md` in this plugin). Do not improvise a format of your
own: the code composes and validates the document, not you.

Arguments received: $ARGUMENTS

If the arguments start with `memory` or `continue`, that is the mode and you do
not have to decide it. Any remaining text is a note from the user about what they
want captured.

If this root holds several projects, a bare `/baton` writes to the session's
active project — the one you loaded with `baton.py load`. With none active the
CLI lists them and stops: pass the project as an argument, or ask the user. Do
not infer it from the files the session touched.
