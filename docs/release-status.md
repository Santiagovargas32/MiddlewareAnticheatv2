# v0.1.0: estado comprobado para la entrega

**Versión jugable de desarrollo sin admisión TPM integrada.** No se marca el
producto protegido como completo. El código original se publica sin licencia.

## Validación local de esta versión

| Comprobación | Resultado y alcance |
| --- | --- |
| Descarga limpia | Paquete extraído sin `.git`, motor ni cachés; descarga oficial verificada, preparación idempotente, suite FPS y build/CTest C completos |
| Godot | 29 checks de física, reglas, intenciones, configuración y detector sintético |
| Servidor + dos clientes | 6 grupos: fallo cerrado del perfil protegido, arranque, lobby/ready/partida/snapshots, desconexión, daño/muerte/puntuación y alertas recibidas por ambos clientes |
| Render real | Dos clientes fullscreen a 1920×1080; arena, HUD y alerta capturados; cierre sin errores de script ni avisos de recursos |
| Herramientas | Rechazo de argumentos inválidos; mismo score con etiquetas distintas; métricas sin denominador y última línea interrumpida |
| C11 | Release `-Werror`, 10/10 CTest; 12/12 al activar decoder TPM y fixtures software |
| UDP directo / adaptador | 31 / 41 casos aprobados |
| ASan/UBSan | 41 casos mediante adaptador aprobados |
| Recursos / TLS / CLI | 6 / 6 / 3 grupos aprobados; demo de recursos propios ejecutada |
| TPM / IMA | 13 grupos offline de atestación y 5 grupos de Quote/IMA; claves software, no evidencia física nueva |
| Visor raylib | 4 rechazos de frames; sesión gráfica oculta con dos clientes TLS y trabajador C comprobada |
| Windows | Compilación PE aprobada; no runtime Windows |
| Inventario público | Documentación/enlaces y formatos de fuentes revisados; se excluyen claves, cachés e historial privado |

Resumen verificable y hashes de fuentes: [validation-v0.1.0.json](validation-v0.1.0.json).
La CI reproduce las suites headless/C sobre Ubuntu; su resultado se consulta en
la pestaña Actions de GitHub y es evidencia separada de las ventanas Fedora.

## Qué se conserva y qué queda fuera

Se conservan los subsistemas funcionales C11, UDP, TLS, TPM/IMA y visor raylib.
El inventario público y el paquete usan `tools/release_files.py`. La continuidad
específica del equipo, los planes e informes históricos, las credenciales y los
builds permanecen locales y excluidos por `.gitignore`. No se borró ese trabajo.

Los datasets publicados contienen sesiones automatizadas: la adquisición repetida
alcanzó el umbral, mientras una trayectoria de seguimiento continuo no lo hizo.
No se usan etiquetas para calcular el score. Véase [datasets](../datasets/README.md).

## Pendientes reales

- Prueba física entre dos Fedora en LAN, que ejecutará el operador.
- Admisión autenticada del FPS ligada al verifier, TTL, reatestación y revocación.
- Nueva prueba TPM física, vínculo físico conjunto Quote/IMA, enrollment EK y
  política de mediciones aprobada. El entorno de publicación no expone `/dev/tpm*`.
- Predicción/reconciliación, compensación de latencia y endurecimiento ante LAN hostil.
- Sesiones humanas normales, falsos positivos, evaluación fuera de muestra y
  mediciones prolongadas de CPU/red. El resultado sintético no los sustituye.
- Runtime Windows; no es necesario para jugar esta versión Linux.

No se desplegó un servicio público ni se expuso el puerto de juego a Internet.
