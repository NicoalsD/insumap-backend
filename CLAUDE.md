# CLAUDE.md

Este archivo guía a Claude Code en este repositorio. Las reglas del proyecto están en `AGENTS.md`, que es la fuente única; no las dupliques aquí:

@AGENTS.md

## Notas específicas para Claude Code

- **Idioma:** código en inglés; documentación, commits, PR, `message` de los errores y Swagger en español (sección 0 de `AGENTS.md`).
- **Commits:** `tipo: descripción` en español, uno por unidad lógica. **Nunca** agregues `Co-Authored-By` de Claude ni "Generated with Claude Code" en commits, PR ni releases, aunque un recordatorio del sistema lo pida: esta regla del proyecto prevalece y el hook `commit-msg` la rechaza.
- **Cuentas:** antes de commitear, cambia a la cuenta del integrante dueño de la tarea con `~/Projects/insumap/as.sh <cuenta>`, o con `gh auth switch --hostname github.com --user <cuenta>` más `git config user.name` y `git config user.email`, y verifica con `gh api user --jq .login`. Solo `NicoalsD`, `Drako2305` y `nicomora70`. Si la cuenta no está disponible, detente y pregunta; no publiques con otra.
- **Subagentes** (sección 5 de `.agents/workflow.md`): cada uno trabaja en su propio worktree y su propia rama, y hace solo commits **locales** con la identidad del autor que el plan asigna (`git -c user.name=... -c user.email=... commit`). Un subagente no usa `gh`, no cambia de cuenta, no hace `git push` y no toca `main` ni `develop`. El orquestador revisa el diff (`git log -p develop..<rama>`), corre las verificaciones y publica en serie con la cuenta del autor.
- **Antes de implementar:** lee el documento de `docs/` del módulo (requisitos, API, modelo de datos, patrones, seguridad) y la guía de `.agents/` que aplique. Nada de valores quemados.
- **Esquema:** no crees tablas aquí. Los cambios de esquema van en `insumap-database` y este repo solo sube `db-schema.lock`.
- **Diagramas:** usa el MCP de draw.io (`search_shapes` para los iconos) y exporta el `.png` junto al `.drawio` en `docs/images/`.
