# Próximos pasos

La planificación vigente está en el [roadmap](development/roadmap.md), con
[estado comprobado](development/project-state.md) y [workflow](development/workflow.md).
MA-000 está integrado en `648ff3c`. [MA-010](development/tasks/MA-010.md) y su
aceptación de la [ADR 0010](adr/0010-attestor-peer-binding.md) como base experimental
están integrados (cierre PR #2, `54c80f4`). [MA-011](development/tasks/MA-011.md)
también está integrado (PR #3, `1f86af9`): extrae la frontera development y el
contexto por conexión, con CI del HEAD y postmerge PASS.

El siguiente candidato es [MA-012](development/tasks/MA-012.md), canal mTLS completo,
IPC y vínculo con el endpoint real del peer. Su ficha define dependencias y
criterios; está READY para un nuevo encargo, sin implementación. Actualizar
origin/main y registrar la base efectiva al iniciar. No arrancar otros paquetes
automáticamente ni habilitar protegido a partir de la aceptación del diseño.

El [registro arena-admission/1](session-admission.md) ya está integrado en la base
`0c3dc77`; no hay que reimplementarlo. Su aplicación al FPS y el vínculo
attestor–peer siguen pendientes. Development continúa como único modo jugable,
sin fallback silencioso desde protegido. Pérdida de admisión no es sanción por cheat.

La etiqueta v0.1.0 y su [informe](validation-v0.1.0.json) son históricos. Nuevos
cambios necesitan evidencia propia; no reescribir la etiqueta ni usar ese informe
para certificarlos. LAN física, Quote/IMA y campaña humana tienen aceptación
separada de CI, pruebas locales y fixtures software.
