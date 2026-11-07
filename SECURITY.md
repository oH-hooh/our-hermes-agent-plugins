# Security Policy

Plugins in this repository act on behalf of a Hermes Agent. `telegram-skill-review`
can approve writes to an agent's own skills, so authorization bypasses, profile
confusion, and replay bugs are treated as security issues.

## Reporting a vulnerability

Report privately through GitHub:
**Security → Report a vulnerability** on
<https://github.com/oH-hooh/our-hermes-agent-plugins/security/advisories/new>.

Do not open a public issue for a vulnerability. Include the plugin name and
version, your Hermes version (`hermes --version`), reproduction steps, and the
impact you observed.

You should receive an acknowledgement within 7 days. Fixes ship as a new plugin
version. For plugins listed in the Hermes plugin catalog, the fix reaches users
after the catalog entry's SHA pin is bumped.

## Supported versions

Only the latest released version of each plugin receives security fixes.

## Scope

In scope: code in this repository. Out of scope: Hermes Agent itself and the
Telegram Bot API. Report those upstream, to
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/security)
and Telegram respectively.
