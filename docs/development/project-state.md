# Estado del proyecto

## MA-012 revisable localmente — 2026-09-23

IN_REVIEW en `feat/ma-012-authenticated-peer-binding`, desde origin/main
`a9baba8808f655b6cba2061a2071902c74edce20`; fetch al retomar confirma la misma base.
MA-010/011 integrados. [Ficha](tasks/MA-012.md) y
[evidencia](ma-012-validation.md): túnel mTLS de todo ENet, IPC heredado acotado,
asociación de certificado/endpoint real y contexto sin permiso. Dos identidades,
reconexión, rechazo directo, muerte del auxiliar y limpieza comprobados en harness.
Protegido público permanece cerrado; arena-admission/1 y gameplay no cambian.

verify_release PASS 10/10, Godot rutas/IPC 49 checks, Python 15 grupos, harness real
12 escenarios. FPS gráfico PASS 6 escenarios con captura inspeccionada; admisión
14 casos y CTest session_admission 1/1 software. La evidencia enlazada identifica
extracción/clone y revisión, sin atribuir CI histórica al diff. Commit local y
texto de PR preparados; publicación/merge de MA-012 no autorizados por la excepción
anterior, que se limitaba a MA-010/011. No hay URL de PR nueva ni integración.

Pendiente: revisión/publicación/integración autorizada; después [MA-013](tasks/MA-013.md)
para barrera y enforcement, [MA-014](tasks/MA-014.md) para lifecycle/medición,
[MA-015](tasks/MA-015.md) para LAN/TPM físicos. Sólo se han escrito sus fichas.
TCP introduce retención y quedan pendientes revocación ≤800 ms y aceptación de
pausas; no son resultados MA-012. Rollback por revert mediante PR manteniendo
protegido cerrado. Los informes siguientes conservan el alcance de sus sesiones.

## Histórico: MA-011 integrado — 2026-09-20

Rama `refactor/ma-011-admission-boundary`, base
`54c80f4a44147a380eff02335a7193851a0d2d3a` desde origin/main actualizado.
[Ficha MA-011](tasks/MA-011.md) definida antes del runtime. Extrae transporte ENet,
admisión development y contexto por conexión; conserva RPC y lógica de partida.
DONE después de comprobar integración por [PR #3](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/pull/3).
Commit `61cbe7baae96dcb1099033b96bbb962d38f1a96b`, merge
`1f86af947c3a4aeedbb864232c53efa01d518027`, ancestry PASS en origin/main.
verify_release PASS 7/7, reglas 29, frontera 59 checks más cinco de
puerto ocupado, FPS gráfico seis escenarios con captura inspeccionada. Build
Release -Werror LAB_TPM=ON y session_admission PASS (software). Paquete de 144
fuentes/hashes extraído limpio con verify_release PASS. Diez RPC idénticas,
diff revisado y documentación PASS. [Ficha](tasks/MA-011.md#evidencia-y-revisión--2026-09-20)
detalla oráculos, artefactos y límites. Clone limpio del commit PASS y
[CI del HEAD](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35519199011)
completed/success, incluidos los gates C/TPM software, integración y sanitizers.
[CI postmerge](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35519343254)
completed/success. No hay bloqueos de MA-011 pendientes.
Rollback por revert de la
refactorización mediante PR. No se habilita protegido ni se implementa MA-012;
es el siguiente candidato [READY](tasks/MA-012.md), con dependencias y criterios
documentados, sin iniciar. Túnel/IPC/identidad y sus E2E siguen pendientes.
Cierre de estado en `docs/ma-011-review-closeout`, sólo documentación desde el
merge comprobado, mediante PR autorizada. El informe histórico se conserva debajo.

## MA-010 cerrado — 2026-09-20

Base remota comprobada: `9c4f7872f3db9cf7c53368e8c115671920253f45`, contiene la
entrega documental MA-010. [CI histórica de ese SHA](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35437664557)
completed/success, consultada nuevamente. MA-010 documental DONE; ADR aceptada
por el titular como base experimental. Se revisaron identidad/IPC/estados/plazos;
se aclara el ACK de rollover y el coste de TCP/suspensión periódica sin afirmar
E2E ni tiempos medidos. T01–T28 y MA-012–015 siguen pendientes.

Rama de cierre: `docs/ma-010-review-closeout`, commit `5c4c4e2`,
[PR #2](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/pull/2) integrada
como `54c80f4a44147a380eff02335a7193851a0d2d3a`; ancestry comprobado tras fetch.
[CI del HEAD](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35518541872)
y [postmerge](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35518644075)
completed/success. El encargo actual autoriza commits,
push de ramas, PR y merge sujeto a controles GitHub para ambos objetivos; nunca
push directo a main ni bypass. Las restricciones siguientes son del informe
histórico conservado, no de esta ejecución. Rollback de cierre: revert documental
mediante PR. No cambia runtime. Validación local: verificador documental.

## Informe histórico de la entrega MA-010 (2026-09-19)

Registro MA-010, 2026-09-19. Rama `docs/ma-010-admission-design`.
Base: `648ff3c06efbadd554cf199c05e16b0663c11af0`, origin/main actualizado al inicio.
Árbol inicial limpio. MA-000 integrado por ancestry (origin/main apunta a su commit);
no se infiere una PR ni se ha hecho merge en esta sesión. La revisión documental
es el commit que incorpora este estado, sin hash circular de sí mismo.

Paquete actual: [MA-010](tasks/MA-010.md), IN_REVIEW. Siguiente candidato: MA-011,
BACKLOG hasta integrar MA-010 y recibir el encargo. [Roadmap](roadmap.md) mantiene
el orden. Juego actual: sólo development; no cambió runtime ni etiqueta v0.1.0.

## Diseño entregado

[ADR 0010](../adr/0010-attestor-peer-binding.md), propuesta para revisión:

- Canal TLS 1.3 mutuo por conexión que transporta todos los datagramas ENet;
  auxiliares Python e IPC por pipes heredados, endpoint local real observado por
  Godot y binding completo. No se confía en ALLOW/fingerprint aportado por cliente.
- Perfil propuesto verified_pinned_ak/1 con límites explícitos: firma fresca y
  asociación lógica, no integridad del proceso, PCR aprobados, IMA remoto ni EK.
- Conexión/partida/ronda separadas; generaciones y epochs impiden aplicar respuestas
  e intenciones viejas. Barrera CHALLENGED server-side para cada renovación;
  rollover a 270 s con nuevo binding y revocación previa, sin extender los 300 s.
- Frescura cacheada máxima 750 ms anclada antes de encolar status; objetivo de
  retirada de acciones ≤800 ms con guard ≤50 ms. Es presupuesto **no medido aún**
  en protegido. Fallo cerrado, suspensión visible, sin sanción por cheat ni fallback.
- [Matriz T01–T28](ma-010-validation.md#matriz-e2e-pendiente), límites de recursos y
  división de MA-011–015. No se implementó ningún paquete posterior.

## Evidencia de esta revisión

[Evidencia detallada, fuentes y comandos de sondeo](ma-010-validation.md).

| Comprobación | Resultado / alcance |
| --- | --- |
| Dependencia MA-000 | PASS: fetch y ancestry de 648ff3c en origin/main |
| Contratos/código | Registro existente confirmado: 7 campos, TTL 300/10/30 s, renovación suspende y sin push; Godot protegido rechazado |
| API Godot 4.7.2 con SHA256 fijado | PASS: 23 firmas; TLSOptions no expone configuración de mTLS cliente |
| Smoke headless de endpoint ENet y pipe no bloqueante | PASS: dos peers loopback y proceso Python propio; no prueba el túnel propuesto |
| Build existente build-tpm | PASS: Release -Werror, LAB_TPM=ON; sin cambios C |
| verificar-admision.py | PASS 14/14, firmas software, TLS local y carreras controladas; no TPM físico |
| verificar-documentacion.py | PASS: 139 archivos públicos y 100 enlaces locales |
| verify_release.py | PASS 6/6 grupos, 29 checks Godot y 6 casos loopback; headless |
| Paquete fuente extraído limpio | PASS: 139 hashes, nuevas guías presentes y privados excluidos; sin cambios al inventario |
| Comandos de sondeo publicados | PASS reproducidos literalmente, con XDG/proyecto temporales y timeout |
| Diff | PASS sin errores de whitespace; sólo 11 archivos Markdown, runtime/CI intactos |

Primer sondeo de reflexión falló al crear directorios de usuario fuera del sandbox;
corregido el ensayo con XDG/proyecto temporal aislado, sin errores después. Los
ensayos de sockets se ejecutan con permisos locales; no se cambia seguridad del
host. Las pruebas negativas nuevas están PENDING, no PASS. No se ejecuta nueva
validación visual, LAN física, TPM físico ni CTest completo; no es evidencia
necesaria para cambiar esta documentación. CI anterior no valida este diff.

## Continuidad y límites

MA-000 terminó su implementación en `648ff3c` y ahora su integración está comprobada;
[ficha histórica](tasks/MA-000.md) conserva los resultados propios (137 fuentes,
90 enlaces, gate 6/6, extracción y clone). Esas cifras no certifican MA-010.
Los hallazgos de red/detector/visual y sus reproducciones pendientes siguen en el
roadmap. No se resetea el detector ni se corrige HOST como trabajo oportunista.

Riesgos actuales de diseño: latencia/retención TCP, confianza de procesos locales,
colisiones/reutilización de rutas y presupuesto del scheduler. La matriz exige
reproducirlos antes de habilitar protegido. No hay bloqueo para revisar MA-010;
E2E, recursos bajo carga y evidencia física quedan para sus paquetes autorizados.
Rollback: revertir el commit documental; no hay migración de datos/runtime/TPM.

Entrega con commit local y [PR preparada](tasks/MA-010.md#pr-preparada); sin push,
PR remota ni merge. Próximo comando de revisión: `git diff origin/main...HEAD`.
Después de integrar MA-010, encargar MA-011 y comenzar con `git fetch origin main`.
