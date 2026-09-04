---
description: Write this session's context handoff — a size-capped document, ready for the next session to pick up without losing the thread.
argument-hint: "[optional note]"
allowed-tools: Bash, Read, Write, Glob, Grep
---

Write this session's handoff following **exactly** the procedure in the `baton`
skill (`skills/baton/SKILL.md` in this plugin). Do not improvise a format of your
own: the code composes and validates the document, not you.

Note from the user, if any: $ARGUMENTS

**`/baton` takes no arguments.** Anything after it is a note: what the user wants
captured, or which mode they want. The mode is your decision unless the note
settles it. The target is the CLI's, resolved from disk: the project loaded this
session, the folder the session is standing in, or the repo itself in an
ordinary repo. When nothing on disk settles it, the command stops and says what
to ask: put that question to the user in one line and pass `--project` yourself.
Never infer the target from the files the session touched, and never ask the
user to type a flag.
