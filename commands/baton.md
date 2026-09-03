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

**Arguments are an override, never a requirement.** A bare `/baton` is the normal
call: you decide the mode, and the CLI resolves which project it belongs to —
the one loaded this session, the one the session is standing in, or the only one
there is. Only when a root holds several and none of that settles it does the
command stop and say so; then ask the user in one line and pass `--project`
yourself. Never infer it from the files the session touched, and never ask the
user to type a flag.
