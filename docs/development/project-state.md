# Estado del proyecto

## Cierre MA-010 en curso — 2026-09-20

Base remota comprobada: `9c4f7872f3db9cf7c53368e8c115671920253f45`, contiene la
entrega documental MA-010. [CI histórica de ese SHA](https://github.com/Santiagovargas32/MiddlewareAnticheatv2/actions/runs/35437664557)
completed/success, consultada nuevamente. MA-010 documental DONE; ADR aceptada
por el titular como base experimental. Se revisaron identidad/IPC/estados/plazos;
se aclara el ACK de rollover y el coste de TCP/suspensión periódica sin afirmar
E2E ni tiempos medidos. T01–T28 y MA-012–015 siguen pendientes.

Rama de cierre: `docs/ma-010-review-closeout`. Su PR/CI/integración se comprobarán
antes de iniciar MA-011 desde main actualizado. El encargo actual autoriza commits,
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
