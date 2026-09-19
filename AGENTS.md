# Desarrollo de MiddlewareAnticheatv2

FPS propio para Linux/Fedora en Godot; attestor/verifier y laboratorio en Python/C11.
Responde en español y entrega cambios verificables dentro del paquete solicitado.

## Al iniciar

1. Lee las instrucciones aplicables sin publicar ni sobrescribir las privadas.
   Inspecciona `git status --short`, rama, remotos (sin exponer credenciales) y
   `git rev-parse HEAD`; conserva WIP, configuración y procesos ajenos.
2. Lee [README](README.md), [próximos pasos](docs/next-steps.md),
   [workflow](docs/development/workflow.md), [roadmap](docs/development/roadmap.md),
   [estado](docs/development/project-state.md) y la ficha del paquete enlazada allí.
   Contrasta planes e informes históricos con el código actual; no rehagas lo integrado.
3. Sitúa las fronteras leyendo [amenazas](docs/threat-model.md),
   [red FPS](docs/game-network-protocol.md), [admisión](docs/session-admission.md),
   [UDP C](docs/lab-udp-protocol.md) y [metodología C](docs/c-methodology.md).
   Después consulta sólo los detalles necesarios del subsistema afectado.
4. Comprueba dependencias integradas en `origin/main` actualizado, alcance y
   aceptación. Un paquete activo por defecto; sin paquete indicado, revisa MA-000
   sin iniciar el roadmap. Usa worktree limpio si hay trabajo ajeno.

## Límites de implementación

- Godot conserva el FPS. El servidor decide física, impactos, reglas y permisos;
  el cliente envía intenciones y presenta estado. No aceptar posiciones, vida o
  víctimas como autoridad. No reescribir ni reorganizar sin necesidad concreta.
- Reutiliza `arena-admission/1`. ALLOW, código de salida, fingerprint o hash
  enviados por el cliente no acreditan acceso. mTLS de control no autentica ENet.
  Antes de habilitar protegido, exige [ADR](docs/adr/README.md) y E2E del binding
  completo con conexión real, generación, vigencia y lifecycle. Nunca fallback
  silencioso a development ni respuestas tardías que reactiven conexiones cerradas.
- TLS, procesos y TPM fuera del tick; colas, consultas e historiales acotados.
  No compares relojes monotónicos de hosts. No inventes criptografía: reutiliza
  OpenSSL/BCrypt/TPM2-TSS. Versiona incompatibilidades y prueba rechazos.
- Mantén separados contratos Godot, C y atestación. C11, Release `-Werror`,
  límites antes de acceso/conversión, EINTR, lectura parcial, entropía y limpieza
  de sockets, memoria, hilos e hijos también en error/timeout.
- El toggle del simulador nunca entra al detector. Conserva LOG_ONLY/WARN,
  falsos negativos y evaluación separada de calibración. Reproduce dos rondas
  antes de decidir un reset. TPM/IMA, autoridad y conducta son evidencias distintas;
  firma válida no demuestra origen hardware ni ausencia de cheats.
- Mide red antes de optimizar. Una arena/arma cuidada antes de ampliar contenido;
  los efectos visuales no cambian colisiones accidentalmente. Documenta origen y
  licencia por asset; no elijas licencia del código propio.
- Preserva secretos, instrucciones privadas, juegos y resultados locales. No
  cambies permisos, arranque, firmware ni estado persistente TPM como reparación.
  Detén sólo procesos propios. No prometas compatibilidad con anticheats ajenos.

## Validación y cierre

Ejecuta `python3 scripts/verificar-documentacion.py` y, si afecta al entregable,
`python3 tools/verify_release.py`. Para visuales/flujo real añade
`python3 tools/verify_game.py --graphical`. Selecciona C/TPM, integración y
sanitizers según la [matriz del workflow](docs/development/workflow.md).
No omitas gates para obtener verde ni confundas headless, render, LAN y hardware.

Actualiza la ficha, [estado](docs/development/project-state.md),
[roadmap](docs/development/roadmap.md) y contratos/ADR afectados con evidencia real,
bloqueos y próximo paso. Revisa diff y staging selectivo; commit local cuando el
paquete esté revisable. Push/PR sólo según autorización en la ficha; nunca merge,
release o reescritura de main/v0.1.0 por inferencia. Antes de merge: IN_REVIEW,
no DONE. Entrega objetivo, rama/base, pruebas, límites, riesgos, rollback y commit.
