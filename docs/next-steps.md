# Próximos pasos

La planificación vigente está en el [roadmap](development/roadmap.md), con
[estado comprobado](development/project-state.md) y [workflow](development/workflow.md).
MA-000 prepara esta metodología; el siguiente trabajo recomendado es
[MA-010: diseño de admisión](development/tasks/MA-010.md), tras integrar MA-000
y recibir su encargo. No iniciar automáticamente los siguientes paquetes.

El [registro arena-admission/1](session-admission.md) ya está integrado en la base
`0c3dc77`; no hay que reimplementarlo. Su aplicación al FPS y el vínculo
attestor–peer siguen pendientes. Development continúa como único modo jugable,
sin fallback silencioso desde protegido. Pérdida de admisión no es sanción por cheat.

La etiqueta v0.1.0 y su [informe](validation-v0.1.0.json) son históricos. Nuevos
cambios necesitan evidencia propia; no reescribir la etiqueta ni usar ese informe
para certificarlos. LAN física, Quote/IMA y campaña humana tienen aceptación
separada de CI, pruebas locales y fixtures software.
