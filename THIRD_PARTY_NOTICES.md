# Third-party notices

AgentOffice is MIT-licensed ([LICENSE](LICENSE)). It depends on open-source packages, each under
its own licence. The full dependency lists are pinned in `backend/requirements.txt` and
`frontend/package.json` / `package-lock.json`.

**Third-party code:** none is copied into this repository. All pixel art is original procedural
art.

**Direct UI dependencies added with the UX redesign (2026-11-25):**

| Package | Version | Licence | Use |
|---|---|---|---|
| `@radix-ui/react-dialog` | 1.3.1 | MIT, © WorkOS | Accessible modal and side drawer (focus trap, Escape, focus restore) |
| `@radix-ui/react-popover` | 1.3.1 | MIT, © WorkOS | Project switcher popover |
| `cmdk` | 1.1.1 | MIT, © Paco Coursey | Searchable project list |

**Design references only, with no code or assets copied** (see docs/UX_OPEN_SOURCE_FOUNDATIONS.md):
- shadcn/ui (MIT): composition patterns;
- Plane (AGPL-3.0);
- Chatwoot (MIT, except its `enterprise/` directory);
- assistant-ui (MIT): composer behaviour.
