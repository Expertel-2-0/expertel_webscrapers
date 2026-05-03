# Historial de Fallos de Scrapers — Análisis Continuo

Documento vivo para rastrear fallos de los scrapers, categorizar errores y descubrir patrones a través de múltiples ejecuciones.

---

## Categorías de Error Identificadas

### CAT-1: Meses anteriores a mayo 2025 (ESPERADO)
- **Síntoma Bills:** `Month <X> not found in year 2025`
- **Síntoma Detail Reports:** `No option found matching pattern: b<YYYYMM>`
- **Causa:** El portal de Telus solo conserva ~12-13 statements recientes. Statements de ene/feb/mar/abr 2025 (e incluso anteriores) ya fueron purgados.
- **Resolución:** No es un bug. Considerar marcar estos jobs como no recuperables.

### CAT-2: Error 403 en upload — empresa/cliente borrado (ESPERADO)
- **Síntoma:** `HTTP 403 - {"error": "An error occurred trying to validate user's client and/or workspace"}`
- **Causa real:** Estos `BillingCycle` pertenecen a **empresas que fueron borradas**. El backend devuelve 403 porque el cliente/workspace asociado ya no existe — no es un problema de permisos del token ni de configuración.
- **Resolución:** No es un bug del scraper ni del backend. La orquestación no debería programar `ScraperJob` para billing cycles cuyo cliente fue borrado. Idealmente, al borrar una empresa, sus jobs pendientes deberían cancelarse / marcarse como obsoletos.

### CAT-3: Fallos de red / infraestructura local
- **Síntoma:** `Timeout waiting for download`, `ERR_NETWORK_CHANGED`, `ERR_NAME_NOT_RESOLVED`, DNS failure a la BD.
- **Causa:** Conectividad local interrumpida durante la ejecución.
- **Resolución:** Reintentar cuando la red sea estable.

### CAT-4: Sesión contaminada — cuenta visible no coincide con la del job
- **Síntoma:** Login marcado como exitoso (`Already logged in after My Telus navigation`), pero al abrir Bills el header muestra una cuenta distinta a la del job. El scraper hace clic en `Change` y luego no encuentra la cuenta esperada en la lista (`Account NOT found in available accounts list`).
- **Causa probable:** El **perfil CDP de Chrome se reutiliza entre runs** (`browser_profiles\telus_cdp_profile`). Si un run previo dejó la sesión abierta con otro usuario, el siguiente run hereda esa sesión aunque el `SessionManager` crea que está logueando con credenciales nuevas. Las credenciales del job actual no llegan a usarse porque "ya está logueado".
- **Resolución pendiente:**
  - Forzar logout limpio al inicio de cada run cuando cambien las credenciales.
  - O bien purgar el perfil CDP cuando el `Active session for Telus with user X` no coincida con el usuario esperado para el job.
  - El check `Already logged in after My Telus navigation` debería verificar **qué usuario** está logueado, no solo que haya sesión activa.

---

## Run #1 — 2026-04-24 16:20 a 16:46 (cuenta 42684921)

**Total:** 6 jobs | **Exitosos:** 3 | **Fallidos:** 3

| Job | Mes | Resultado | Categoría |
|-----|-----|-----------|-----------|
| 214 | Abr 2025 | 1/3 | CAT-1 |
| 208 | Jul 2025 | 3/3 ✅ | — |
| 216 | Mar 2025 | 1/3 | CAT-1 |
| 210 | Jun 2025 | 3/3 ✅ | — |
| 212 | May 2025 | 3/3 ✅ | — |
| 218 | Feb 2025 | 0/3 | CAT-1 |

**Notas:**
- Cuenta 42684921 funciona bien para upload (cycles 110, 112, 113, 114).
- Statements disponibles desde ~jul 2025 hacia el futuro en Detail Reports dropdown.

---

## Run #2 — 2026-04-24 16:53 a 17:00 (cuenta 42246831)

**Total:** 2 jobs | **Exitosos:** 0 | **Fallidos:** 2

| Job | Mes | Resultado | Categoría |
|-----|-----|-----------|-----------|
| 684 | Feb 2025 | 0/3 | CAT-1 |
| 686 | Ene 2025 | 0/3 | CAT-1 |

**Notas:** Solo se procesaron meses no recuperables. No se probó ningún upload con esta cuenta.

---

## Run #3 — 2026-04-24 17:02 a 17:40 (cuenta 39931076 — `expertel@buhlerindustries.com`)

**Total:** 11 jobs (9 procesados antes de crash de red) | **Exitosos:** 0 | **Fallidos:** 9

| Job | Mes | Descargados | Subidos | Categoría |
|-----|-----|-------------|---------|-----------|
| 698 | Ago 2025 | 3/3 | 0/3 | CAT-2 (cycle 363) |
| 696 | Sep 2025 | 3/3 | 0/3 | CAT-2 (cycle 362) |
| 694 | Oct 2025 | 3/3 | 0/3 | CAT-2 (cycle 361) |
| 692 | Nov 2025 | 3/3 | 0/3 | CAT-2 (cycle 360) |
| 706 | Abr 2025 | 1/3 | 0/1 | CAT-1 + CAT-2 (cycle 367) |
| 688 | Ene 2026 | 3/3 | 0/3 | CAT-2 (cycle 358) |
| 690 | Dic 2025 | 3/3 | 0/3 | CAT-2 (cycle 359) |
| 712 | Ene 2025 | 0/3 | 0/0 | CAT-1 |
| 704 | May 2025 | 0/3 | 0/0 | CAT-3 (red cayó durante descarga) |

**Hallazgo crítico:** TODOS los uploads de la cuenta 39931076 fallan con 403. Cycles afectados: 358, 359, 360, 361, 362, 363, 367.

**Notas:**
- Job 694: el archivo Mobility Device se descargó como `detail_report.csv` en vez de `Mobility Device Summary Report.csv` — Telus a veces cambia el nombre del export. No causó el fallo del job (fue el 403), pero observar.
- Job 704: timeout de descarga de mayo 2025 → cascada de errores de red → DNS failure a la BD (`ec2-3-142-119-179.us-east-2.compute.amazonaws.com`) → excepción no capturada que mató el proceso. Jobs 10 y 11 nunca arrancaron.

---

## Run #4 — 2026-04-24 18:12 a 18:14 (cuenta 39906511, INTERRUMPIDO)

**Total:** 5 jobs disponibles | **Procesados:** 1 (interrumpido con Ctrl+C)

| Job | Mes | Resultado | Categoría |
|-----|-----|-----------|-----------|
| 732 | Abr 2025 | interrumpido (Ctrl+C durante Part 2) | CAT-1 (Bills falló) |

**Notas:** El usuario logueado en este run quedó persistido en el perfil CDP — esto contaminó el Run #5 (ver abajo).

---

## Run #5 — 2026-04-24 18:17 a 18:23 (cuenta 42684921 — `Expertelteam`) ⚠️ NUEVO PATRÓN

**Total:** 3 jobs | **Exitosos:** 0 | **Fallidos:** 3 (TODOS marcados como ERROR permanente, max retries 3/3 alcanzado)

| Job | Mes | Resultado | Categoría |
|-----|-----|-----------|-----------|
| 214 | Abr 2025 | 0/3 → ERROR permanente | CAT-4 |
| 216 | Mar 2025 | 0/3 → ERROR permanente | CAT-4 |
| 218 | Feb 2025 | 0/3 → ERROR permanente | CAT-4 |

**Hallazgo crítico — CAT-4 detectado por primera vez:**
- El scraper afirma `Authentication successful` con usuario `Expertelteam` (correcto para 42684921).
- Pero al navegar a Bills, el header muestra `Account #39906511Change` — cuenta del Run #4 anterior.
- El scraper detecta el mismatch e intenta cambiar de cuenta, pero `42684921 NOT found in available accounts list`.
- **Causa:** el perfil CDP `telus_cdp_profile` arrastró la sesión del Run #4 (usuario distinto, otra cuenta). El "login" del Run #5 fue un no-op porque la sesión del usuario anterior seguía viva en el perfil.

**Daño colateral:** estos 3 jobs ya habían fallado en Run #1 con CAT-1 (meses no recuperables). En Run #5 fallaron por CAT-4. Al sumar 3 retries, fueron marcados como **ERROR permanente** — pero la causa raíz del fallo permanente fue CAT-4, no CAT-1. Si se purgara el perfil CDP, se podría reintentar (aunque seguirían fallando por CAT-1).

---

## Run #6 — 2026-04-24 18:24 a 18:31 (cuenta 42246831 — `cellphones@cogir.net`)

**Total:** 2 jobs | **Exitosos:** 0 | **Fallidos:** 2 (TODOS marcados como ERROR permanente, max retries 3/3 alcanzado)

| Job | Mes | Resultado | Categoría |
|-----|-----|-----------|-----------|
| 684 | Feb 2025 | 0/3 → ERROR permanente | CAT-1 |
| 686 | Ene 2025 | 0/3 → ERROR permanente | CAT-1 |

**Notas:**
- Login limpio con credenciales (sin contaminación de sesión). El Run #5 anterior cerró sesión correctamente con `Logout successful in Telus` antes de salir, por lo que el perfil CDP entró sin sesión heredada → CAT-4 NO se reprodujo aquí.
- Ambos jobs son meses no recuperables del portal (statements más antiguos disponibles: `b20250627` para esta cuenta). Después de 3 intentos quedaron como ERROR permanente — outcome correcto para CAT-1.
- Confirmado: **CAT-4 solo aparece cuando el run previo no termina con logout limpio.**

---

## Run #7 — 2026-04-24 18:34+ (cuenta 39931076 — `expertel@buhlerindustries.com`) — PARCIAL

**Total mostrado:** 2 de 9 jobs disponibles | **Exitosos:** 0 | **Fallidos:** 1 confirmado, 1 en progreso

| Job | Mes | Resultado | Categoría | Notas |
|-----|-----|-----------|-----------|-------|
| 698 | Ago 2025 | 3/3 desc, 0/3 upload → ERROR permanente | CAT-2 (cycle 363) | **Retry 3/3 alcanzado.** Mismo 403 que en Run #3. |
| 712 | Ene 2025 | en progreso (log cortado) | esperado CAT-1 | — |

**Hallazgo importante:** el 403 de CAT-2 NO es transitorio — Run #3 lo registró por primera vez (retry 2/3) y Run #7 lo reproduce idéntico (retry 3/3 → ERROR permanente). Confirma que es un problema de configuración del backend, no un fallo temporal. La urgencia de investigar permisos del token / asociación cliente-workspace para cycle 363 (y los demás cycles de la cuenta 39931076) sube a **bloqueante**.

**Notas de sesión:** primer job (698) hizo login limpio con credenciales (`Login successful in Telus` con `expertel@buhlerindustries.com`), no hubo CAT-4 — el Run #6 anterior cerró sesión correctamente. Segundo job (712) reusa sesión correctamente (`Active session for Telus with user expertel@buhlerindustries.com`).

---

## Cuentas con problema de upload (CAT-2 — empresa borrada)

| Cuenta | Email | Cycles afectados | Estado |
|--------|-------|------------------|--------|
| 39931076 | expertel@buhlerindustries.com | 358, 359, 360, 361, 362, 363, 367 | ⚠️ Empresa borrada — los uploads fallan con 403 esperado. Los jobs deberían cancelarse en el orquestador. |

## Cuentas que funcionan correctamente

| Cuenta | Cycles probados | Estado |
|--------|-----------------|--------|
| 42684921 | 110, 111, 112, 113, 114 | ✅ Upload OK (cuando la sesión no está contaminada) |

## Cuentas afectadas por contaminación de sesión (CAT-4)

| Run | Cuenta esperada | Usuario esperado | Cuenta vista en portal | Causa |
|-----|-----------------|------------------|------------------------|-------|
| #5  | 42684921 | Expertelteam | 39906511 (de Run #4) | Perfil CDP heredado |

---

## Patrones observados (a actualizar)

1. **Disponibilidad de statements en el portal de Telus:**
   - Dropdown "Detail Reports" guarda ~29 opciones (~2 años)
   - Sección "Bills" parece guardar menos historial
   - Statement más antiguo visto en 39931076: `b20250717` (jul 2025)
   - Statement más antiguo visto en 42246831: `b20250627` (jun 2025)
   - Statement más antiguo visto en 42684921: `b20250721` (jul 2025)

2. **403 en upload** ocurre porque la empresa asociada al `BillingCycle` fue borrada. El backend rechaza correctamente el upload — el problema está aguas arriba: la orquestación sigue programando jobs para empresas que ya no existen.

3. **Nombre del archivo Mobility Device:** normalmente `Mobility Device Summary Report.csv`, pero ocasionalmente `detail_report.csv` (visto 1 vez en job 694).

4. **Perfil CDP compartido entre runs:** cuando un run termina sin logout limpio (Ctrl+C, crash de red, etc.), el siguiente run con credenciales distintas hereda la sesión anterior. El check de "Already logged in" no valida qué usuario está logueado.

5. **`Cleaned existing directory for job_<N>`:** apareció por primera vez en Run #5 — el scraper limpia carpetas de descarga previas antes de escribir, lo cual está bien.

6. **CAT-4 vs logout limpio:** confirmado en Run #6 — cuando el run anterior cierra sesión correctamente, el siguiente arranca sin contaminación. Por eso 42246831 entró bien después de que Run #5 terminó con `Logout successful in Telus`.

7. **Comportamiento de "Find your account" screen:** aparece la primera vez que se hace click en text-bill (Run #1, Run #2, Run #4 turn 1, Run #6 turn 1). En jobs subsiguientes del mismo run no aparece (la cuenta queda fijada). En Run #5 NO apareció aunque era el primer job — síntoma adicional de la contaminación CAT-4.

---

## Acciones pendientes

### Críticas
- [ ] **CAT-2:** En el orquestador, cancelar / marcar como obsoletos los `ScraperJob` cuyo `BillingCycle` pertenezca a una empresa borrada. Idealmente, hookear el borrado de empresas para limpiar jobs pendientes. Mientras tanto, los retries seguirán consumiéndose y los jobs caerán en ERROR permanente (caso ya visto en Run #7 con cycle 363).
- [ ] **CAT-4:** Validar el usuario logueado en el perfil CDP antes de reusar la sesión. Si no coincide con el esperado para el job, forzar logout + login limpio. Considerar también purgar el perfil CDP cuando el run anterior no terminó con logout exitoso.

### Importantes
- [ ] **CAT-1:** Decidir política para meses no recuperables: ¿detectar que el statement no existe en el portal y marcar el job como `permanently_failed` sin consumir 3 retries?
- [ ] **CAT-3:** Capturar `KeyboardInterrupt` y errores de DNS en `main.py` para evitar excepciones no manejadas que matan el proceso (Run #3 perdió 2 jobs por esto).
- [ ] Revisar jobs 214/216/218 marcados como ERROR permanente en Run #5 — el motivo permanente fue CAT-4, no CAT-1. Quizá deban des-marcarse y reintentarse después de arreglar la contaminación de sesión.
- [ ] Jobs 684/686 marcados como ERROR permanente en Run #6 son legítimamente CAT-1 (meses no recuperables) — esos sí deben quedarse como ERROR.

### Investigación
- [ ] Por qué job 694 descargó `detail_report.csv` en vez del nombre estándar.
- [ ] Por qué cuenta 42684921 (que en Run #1 mostró "Find your account" screen) en Run #5 NO mostró ese screen — el portal entró directo a la cuenta equivocada.