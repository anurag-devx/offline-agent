# Security

offline-agent runs AI models that can act on your computer, so safety is part of the design:
permissions are enforced in code (not by prompts), credential folders are always blocked,
nothing is overwritten, delete goes to the Trash, and every action is recorded.

**Found a way around a permission, scope or protected location?** Please don't open a public
issue. Use GitHub's private vulnerability reporting (Security tab → Report a vulnerability).

Known limits:
- Anything an agent puts in a web address it opens reaches that site. Use "Ask first" for
  internet on agents that read private data (the validator warns about this).
- Email app passwords are stored unencrypted in `~/.offline-agent/credentials.json` (chmod 600).
