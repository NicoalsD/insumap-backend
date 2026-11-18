# Cumplimiento y privacidad

Este documento resume el marco normativo colombiano que Insumap toma como referencia y lo traduce en controles concretos del sistema. Aplica a los cinco repositorios. Los controles técnicos se describen en [`Seguridad.md`](Seguridad.md); aquí se remite a sus secciones y no se repiten.

> **Aviso 1, análisis académico:** este documento es un análisis académico hecho por estudiantes. **No es asesoría jurídica** ni un concepto legal. Antes de cualquier piloto con una clínica real, un abogado con experiencia en protección de datos y en salud debe revisarlo.
>
> **Aviso 2, datos simulados:** Insumap es un proyecto académico, no es un dispositivo médico y todos sus pacientes son simulados ([`Datos-simulados.md`](Datos-simulados.md)). Hoy no se tratan datos personales reales. Las obligaciones de este documento se diseñan como si lo fueran, porque los datos de salud son datos sensibles y el diseño debe poder usarse con datos reales sin rehacerlo.

Documentos relacionados: [`Seguridad.md`](Seguridad.md), [`Insumap.md`](Insumap.md), [`Requerimientos.md`](Requerimientos.md), [`Riesgos.md`](Riesgos.md) (RG-05), [`Actores-y-permisos.md`](Actores-y-permisos.md), [`Modulo-IA.md`](Modulo-IA.md), [`Contrato-IA.md`](Contrato-IA.md), [`Datos-simulados.md`](Datos-simulados.md) y [`Stack-tecnologico.md`](Stack-tecnologico.md).

## 1. Método y estados de cada afirmación

Cada afirmación legal de este documento tiene uno de estos estados:

| Estado | Significado |
|---|---|
| **Verificado** | Se leyó el texto de la norma en una fuente oficial o en el normograma de una entidad pública, el 2026-11-18. La sección 3 lista la URL exacta que se abrió |
| **Interpretación** | Es la lectura del equipo sobre cómo aplica una norma verificada a Insumap. Necesita revisión jurídica |
| **Propuesta** | Es una decisión de diseño de Insumap, no una exigencia legal verificada |
| **Pendiente de verificar** | No se pudo confirmar. No se afirma |

Límites del método:

- Los sitios `secretariasenado.gov.co`, `funcionpublica.gov.co` y `suin-juriscol.gov.co` no se pudieron abrir desde el entorno de trabajo (error de conexión o de certificado). Los textos se leyeron en el Gestor Normativo de la Alcaldía de Bogotá y en los normogramas de la Superintendencia Nacional de Salud, el INVIMA, la Cancillería, Colpensiones y la CRA, que reproducen el texto oficial con sus notas de vigencia.
- Un normograma puede ir por detrás del Diario Oficial. La vigencia posterior a la fecha de cada compilación es **pendiente de verificar** y se revisa antes de un piloto real.
- Ninguna cifra legal de este documento se copió de memoria. Donde una cifra no se pudo confirmar, aparece como "pendiente de verificar".

## 2. Resumen

| Tema | Conclusión | Estado |
|---|---|---|
| Naturaleza de los datos | Los datos de salud son **datos sensibles** (Ley 1581 de 2012, art. 5). Su tratamiento está prohibido salvo las excepciones del art. 6, y la principal es la autorización explícita | Verificado |
| Roles | La clínica es la **responsable** del tratamiento e Insumap es la **encargada** (Ley 1581, art. 3 literales d y e). Entre ambas hay una **transmisión** de datos con contrato, no una transferencia | Verificado (roles); interpretación (aplicación a Insumap) |
| Autorización | Debe ser previa, expresa e informada, con prueba conservada, y no puede condicionarse la actividad a entregar datos sensibles (Decreto 1377 de 2013, art. 6) | Verificado |
| Derechos del titular | Consultas en 10 días hábiles y reclamos en 15 días hábiles, con prórrogas máximas de 5 y 8 días hábiles | Verificado |
| Historia clínica | Es reservada (Resolución 1995 de 1999, art. 1). Se conserva mínimo 15 años desde la última atención (Resolución 839 de 2017, art. 3), 5 en archivo de gestión y 10 en archivo central | Verificado |
| Historia clínica electrónica | La Ley 2015 de 2020 exige que las correcciones se agreguen sin borrar lo corregido (art. 8, parágrafo 1) | Verificado |
| Telesalud | Una plataforma tecnológica queda bajo la responsabilidad de quien presta el servicio de salud (Resolución 2654 de 2019, art. 21). Insumap sería un proveedor tecnológico de la clínica | Verificado (texto); interpretación (aplicación) |
| Dispositivo médico | El Decreto 4725 de 2005 incluye al software entre los dispositivos médicos según el uso que proponga el fabricante. **No se concluye** que Insumap quede fuera: se mitiga con el uso académico, los datos simulados y la ausencia de comercialización | Verificado (definición); interpretación (riesgo) |
| Transferencia internacional | Alojar en Render, Neon o Vercel es una **transmisión** al encargado con contrato. Enviar datos a un proveedor de LLM que los use para sus propios fines sería una **transferencia** (Ley 1581, art. 26) | Verificado (reglas); interpretación (aplicación) |
| Estados Unidos como país adecuado | Figura en la lista de la SIC de 2017. Su vigencia actual es pendiente de verificar | Verificado (2017); pendiente (hoy) |
| Brechas | Se informa a la SIC (Ley 1581, art. 17 literal n y art. 18 literal k). El reporte al RNBD es en 15 días hábiles desde la detección | Verificado |
| Notificación a los titulares | No se encontró una norma que la exija de forma general | Pendiente de verificar |

## 3. Normas verificadas y fuentes abiertas

Todas las URL de esta tabla se abrieron y se leyeron. Los artículos citados salen del texto leído.

| Norma | Artículos usados | URL abierta |
|---|---|---|
| **Ley 1581 de 2012** (Estatutaria, protección de datos personales). Diario Oficial 48587 del 18 de octubre de 2012 | 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15, 17, 18, 25, 26 | `https://www.alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=49981` y `https://normograma.supersalud.gov.co/compilacion/docs/ley_1581_2012.htm` |
| **Decreto 1377 de 2013** (reglamenta parcialmente la Ley 1581). Diario Oficial 48834 del 27 de junio de 2013. Compilado casi todo en el **Decreto 1074 de 2015** (Título 2.2.2.25) | 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 15, 21, 23, 24, 25, 26, 27 | `https://cancilleria.gov.co/sites/default/files/Normograma/docs/decreto_1377_2013.htm` |
| **Decreto 1074 de 2015**, capítulos 25 y 26 (RNBD), con las modificaciones del **Decreto 90 de 2018** | 2.2.2.25.5.1, 2.2.2.25.5.2, 2.2.2.26.1.2, 2.2.2.26.1.3, 2.2.2.26.2.1, 2.2.2.26.3.1 | `https://normativa.colpensiones.gov.co/colpens/docs/decreto_1074_2015_pr026.htm` |
| **Circular Externa 3 de 2018** de la SIC (Diario Oficial 50672 del 1 de agosto de 2018), que modifica el Capítulo Segundo del Título V de la Circular Única | Capítulo Segundo, numeral 2.1 literal f (novedades e incidentes de seguridad) | `https://normas.cra.gov.co/Gestor/Docs/circular_superindustria_0003_2018.htm` |
| **Circular Externa 8 de 2017** de la SIC (Diario Oficial 50448 del 15 de diciembre de 2017), que modifica el numeral 3.2 del Capítulo Tercero del Título V (lista de países con nivel adecuado) | Numeral 3.2 | `https://normas.cra.gov.co/gestor/docs/circular_superindustria_0008_2017.htm` |
| **Concepto de la SIC sobre la Circular Externa 2 de 2025** (boletín jurídico, publicado el 2026-02-25) | Solo el resumen de su alcance | `https://sedeelectronica.sic.gov.co/publicaciones/boletin-juridico/concepto/alcance-de-la-circular-002-de-2025-sobre-transferencias-internacionales-de-datos` |
| **Resolución 1995 de 1999** del Ministerio de Salud (8 de julio de 1999) | 1, 2, 3, 6, 9, 11, 13, 14, 15, 16, 18 | `https://www.unidadvictimas.gov.co/wp-content/uploads/Documentos/resoluciones/RESOLUCI%c3%93N_1995_1999.pdf` |
| **Resolución 839 de 2017** de los Ministerios de Salud y de Cultura (23 de marzo de 2017) | 3, 6, 10, 14 | `https://normativa.colpensiones.gov.co/colpens/docs/resolucion_minsaludps_0839_2017.htm` |
| **Ley 2015 de 2020** (historia clínica electrónica interoperable). Diario Oficial 51213 del 31 de enero de 2020 | 3, 4, 6, 7, 8, 9, 12, 13 | `https://normograma.supersalud.gov.co/compilacion/docs/ley_2015_2020.htm` |
| **Resolución 866 de 2021** de los Ministerios de Salud y de las TIC (25 de junio de 2021) | 10, 17, 18, 19, 22, 26 | `https://normograma.supersalud.gov.co/compilacion/docs/resolucion_minsaludps_0866_2021.htm` |
| **Ley 1419 de 2010** (telesalud). Diario Oficial 47922 del 13 de diciembre de 2010 | 2 | `https://normograma.supersalud.gov.co/compilacion/docs/ley_1419_2010.htm` |
| **Resolución 2654 de 2019** del Ministerio de Salud (telesalud y telemedicina). Diario Oficial 51096 del 4 de octubre de 2019 | 2, 3, 6, 7, 9, 18, 21, 22, 24 | `https://normograma.supersalud.gov.co/compilacion/docs/resolucion_minsaludps_2654_2019.htm` |
| **Decreto 4725 de 2005** (dispositivos médicos). Diario Oficial 46134 del 27 de diciembre de 2005 | 2, 5, 7 (regla 10), 16, 17 | `https://normograma.invima.gov.co/compilacion/docs/decreto_4725_2005.htm` |

No se necesitó la Ley 1266 de 2008 (datos financieros y crediticios) ni la Ley 1712 de 2014 (transparencia). La Ley 1581 excluye de su ámbito las bases reguladas por la Ley 1266 (art. 2).

## 4. Roles legales

### 4.1 Responsable y encargado

Verificado (Ley 1581, art. 3):

- **Responsable del tratamiento** (literal e): quien "decida sobre la base de datos y/o el Tratamiento de los datos".
- **Encargado del tratamiento** (literal d): quien realiza el tratamiento "por cuenta del Responsable".

Interpretación para Insumap, coherente con [`Insumap.md`](Insumap.md):

| Rol | Quién | Por qué |
|---|---|---|
| Responsable | La **clínica** (cliente B2B) | Decide qué pacientes importa, para qué los usa y quién del personal los ve. Conserva la propiedad de los datos |
| Encargado | **Insumap** | Procesa los datos por cuenta de la clínica y bajo sus instrucciones |
| Titular | El **paciente** | Es la persona natural cuyos datos se tratan |
| Subencargados | Render, Neon, Vercel, el proveedor de correo y el proveedor del LLM | Procesan datos por cuenta de Insumap. La norma leída solo regula el vínculo responsable-encargado. La cadena de subencargados es **pendiente de verificar** y se cubre por contrato (sección 11.3) |

Matices:

1. **El contrato de transmisión.** El Decreto 1377, art. 25, exige que el contrato entre el responsable y el encargado fije el alcance del tratamiento, las actividades del encargado y sus obligaciones, y que el encargado se comprometa a aplicar la política del responsable, a tratar los datos según la finalidad autorizada y a proteger su seguridad y confidencialidad. El art. 25 no está compilado en el Decreto 1074; el art. 2.2.2.25.5.2 del Decreto 1074 recoge un contenido equivalente. Insumap necesita un contrato de este tipo con cada clínica (propuesta de plantilla en la sección 17).
2. **La clínica demo.** En la clínica demo (`is_demo = true`) el mismo equipo opera la plataforma y simula a la clínica. La Ley 1581, art. 18, parágrafo, dice que si concurren las dos calidades en la misma persona, se le exigen los deberes de ambas. Es una interpretación sin efecto práctico hoy, porque los datos son simulados, pero explica por qué el diseño aplica los deberes de las dos calidades.
3. **Responsabilidad ante el titular.** El responsable debe "garantizar al Titular, en todo tiempo, el pleno y efectivo ejercicio del derecho de hábeas data" (art. 17 literal a, y art. 18 literal a para el encargado). Por eso Insumap ofrece las herramientas y la clínica tramita las solicitudes (sección 6).

### 4.2 Persona o área de protección de datos

El Decreto 1377, art. 23, obliga a todo responsable y encargado a designar una persona o área que dé trámite a las solicitudes de los titulares. Propuesta: la clínica designa la suya; Insumap designa un contacto de privacidad en su canal de seguridad (`SECURITY.md`, pendiente en [`Seguridad.md`](Seguridad.md), sección 21). La designación concreta queda por definir.

## 5. Datos sensibles y autorización

### 5.1 Qué dice la norma (verificado)

- **Dato personal:** cualquier información vinculada o que pueda asociarse a personas naturales determinadas o determinables (Ley 1581, art. 3 literal c).
- **Dato sensible:** el que afecta la intimidad o cuyo uso indebido puede generar discriminación, e incluye "los datos relativos a la salud" (art. 5; repetido en el Decreto 1377, art. 3 numeral 3).
- **Prohibición y excepciones:** el tratamiento de datos sensibles está prohibido salvo, entre otras, la autorización explícita del titular (art. 6 literal a) y el interés vital del titular incapacitado (literal b).
- **Principios** (art. 4): legalidad, finalidad, libertad, veracidad o calidad, transparencia, acceso y circulación restringida, seguridad y confidencialidad.
- **Autorización:** previa e informada, obtenida por un medio que permita su consulta posterior (art. 9). El silencio no es una conducta inequívoca (Decreto 1377, art. 7).
- **Qué se informa al pedirla** (art. 12): el tratamiento y su finalidad, el carácter facultativo de las respuestas sobre datos sensibles o de menores, los derechos del titular y la identificación del responsable. El responsable conserva prueba de ello.
- **Datos sensibles** (Decreto 1377, art. 6): hay que informar que el titular no está obligado a autorizar, decirle de forma explícita y previa cuáles datos son sensibles y para qué finalidad, y obtener su consentimiento expreso. "Ninguna actividad podrá condicionarse a que el Titular suministre datos personales sensibles."
- **Prueba:** el responsable conserva la prueba de la autorización (Decreto 1377, art. 8).
- **Finalidad nueva:** si cambia la finalidad se necesita una nueva autorización (Decreto 1377, art. 5).
- **Limitación de la recolección:** solo datos pertinentes y adecuados para la finalidad (Decreto 1377, art. 4).
- **Excepciones a la autorización** (Ley 1581, art. 10): entre ellas, los casos de urgencia médica o sanitaria (literal c). Insumap no se apoya en esas excepciones.

### 5.2 La tensión del consentimiento obligatorio (interpretación)

[`Seguridad.md`](Seguridad.md), sección 3.4, exige `accepted: true` para activar la cuenta y responde `403 CONSENT_REQUIRED` si falta. El Decreto 1377, art. 6, prohíbe condicionar una actividad a que el titular entregue datos sensibles, y la Ley 1581, art. 12 literal b, exige informar el carácter facultativo de las respuestas sobre datos sensibles. Estas dos reglas parecen chocar con un consentimiento obligatorio.

Lectura propuesta, **que necesita revisión jurídica**:

1. La autorización cubre el uso de la **aplicación de Insumap**, que es opcional para el paciente. La atención clínica del paciente en la clínica no depende de ella.
2. El aviso de privacidad debe decirlo de forma expresa: que no está obligado a autorizar el tratamiento de sus datos de salud en la aplicación y que negarse **no afecta su atención** en la clínica. Sin ese texto, el consentimiento obligatorio no es defendible.
3. Si el paciente no acepta, la cuenta queda `INVITED` y la clínica sigue atendiéndolo por sus medios habituales (ver [`Seguridad.md`](Seguridad.md), sección 3.1).
4. Mientras esta lectura no se revise, la actividad que se condiciona es solo el uso de la app, nunca la atención.

### 5.3 Clasificación y consecuencias en el sistema

La clasificación P, I, C, H y S de [`Seguridad.md`](Seguridad.md), sección 1.2, ya trata como sensibles los registros de glucosa, insulina, comidas, actividad, síntomas, alertas, mensajes y salidas de la IA (clase H). Por ser sensibles:

- Solo los lee el paciente o su equipo de atención y cada lectura queda auditada ([`Seguridad.md`](Seguridad.md), secciones 6.3 y 7.1).
- No salen hacia la IA con identificadores directos ([`Seguridad.md`](Seguridad.md), sección 9).
- No aparecen en logs, correos ni notificaciones push.

## 6. Derechos del titular y plazos

### 6.1 Derechos y plazos (verificado)

| Derecho o trámite | Regla | Fuente |
|---|---|---|
| Conocer, actualizar y rectificar | Frente al responsable y al encargado | Ley 1581, art. 8 literal a |
| Prueba de la autorización | El titular puede pedirla | Art. 8 literal b |
| Ser informado del uso de sus datos | Previa solicitud | Art. 8 literal c |
| Queja ante la SIC | Solo después de agotar la consulta o el reclamo ante el responsable o el encargado | Art. 8 literal d y art. 16 |
| Revocar la autorización y pedir la supresión | En todo momento, mediante un reclamo. No procede si el titular tiene un deber legal o contractual de permanecer en la base de datos | Art. 8 literal e; Decreto 1377, art. 9 |
| Acceso gratuito | Mecanismos permanentes y ágiles. Gratis al menos una vez por mes calendario | Art. 8 literal f; Decreto 1377, art. 21 |
| **Consulta** | Se atiende en máximo **10 días hábiles**. Si no es posible, se informa el motivo y una nueva fecha, que no supera **5 días hábiles** más | Art. 14 |
| **Reclamo** (corrección, actualización, supresión o incumplimiento) | Si está incompleto, se pide subsanar dentro de **5 días**; si pasan **2 meses** sin respuesta se entiende desistido. Si el receptor no es competente, traslada en **2 días hábiles**. Una vez completo, se marca "reclamo en trámite" en **2 días hábiles**. Se resuelve en máximo **15 días hábiles**, con prórroga de máximo **8 días hábiles** | Art. 15 |
| Actualización por el encargado | El encargado actualiza lo reportado por el responsable en **5 días hábiles** desde su recibo | Art. 18 literal d |
| Legitimación | El titular (acredita su identidad), sus causahabientes, su representante o apoderado, o por estipulación a favor de otro. Los derechos de los menores los ejercen quienes estén facultados para representarlos | Decreto 1377, art. 20 |

### 6.2 Cómo los atiende Insumap

- Los plazos son los de la **clínica** como responsable. Insumap, como encargada, debe poder responder a tiempo a lo que la clínica le pida (propuesta: objetivo interno de 3 días hábiles para cada tarea técnica, para que la clínica cumpla sus 10 y 15 días hábiles).
- RF-93 y HU-53 piden una solicitud del titular con **estado y plazo**, tramitada por la clínica. Los plazos de la tabla anterior se guardan como parámetros en la base de datos (regla "sin valores quemados" de [`AGENTS.md`](../AGENTS.md), sección 3.2), no en el código.
- La exportación entrega los datos en JSON y FHIR (RF-93). El descifrado del documento queda auditado como `DECRYPT` ([`Seguridad.md`](Seguridad.md), sección 8.1).
- Las rutas de las solicitudes del titular están **por definir** en `API.md`. Este documento no inventa sus nombres.
- La **supresión** choca con la conservación de la historia clínica (sección 8). Cuando hay un deber legal de conservar, la supresión no procede (Decreto 1377, art. 9). Insumap responde con la política de retención de la sección 15, nunca con un borrado silencioso.

## 7. Deberes, política, aviso, RNBD y responsabilidad demostrada

### 7.1 Deberes (verificado)

| Deber | Responsable (art. 17) | Encargado (art. 18) |
|---|---|---|
| Copia de la autorización | Literal b | No aplica |
| Informar la finalidad y los derechos | Literal c | No aplica |
| Seguridad contra adulteración, pérdida, consulta o acceso no autorizado o fraudulento | Literal d | Literal b |
| Manual interno de políticas y procedimientos, en especial para consultas y reclamos | Literal f | Literal f |
| Marcar "reclamo en trámite" | Literal g | Literal g |
| Permitir el acceso solo a quien puede tenerlo | No aplica | Literal j |
| **Informar a la SIC de violaciones a los códigos de seguridad con riesgos** | **Literal n** | **Literal k** |
| Cumplir las instrucciones de la SIC | Literal o | Literal l |

### 7.2 Política de tratamiento y aviso de privacidad (verificado)

- La política consta por escrito, en lenguaje claro, y trae como mínimo seis contenidos: identificación del responsable, tratamiento y finalidad, derechos, área de atención, procedimiento para ejercer los derechos y vigencia de la política y de la base (Decreto 1377, art. 13). Un cambio sustancial se comunica antes de aplicarlo.
- El aviso de privacidad informa la identidad y contacto del responsable, el tratamiento y la finalidad, los derechos y cómo consultar la política. Con datos sensibles debe señalar expresamente que responder es facultativo (Decreto 1377, art. 15).
- En Insumap, el **aviso versionado** es el texto que ve el paciente al activar su cuenta ([`Seguridad.md`](Seguridad.md), sección 3.4) y la clínica es su autora. Insumap provee la plantilla y la versión (`privacy_notice_version_id`). Contenido mínimo en la sección 14.3.

### 7.3 Registro Nacional de Bases de Datos (RNBD)

Verificado:

- Deben inscribir sus bases los responsables que sean **sociedades y entidades sin ánimo de lucro con activos totales superiores a 100.000 UVT** y las **personas jurídicas de naturaleza pública** (Decreto 1074, art. 2.2.2.26.1.2, modificado por el Decreto 90 de 2018).
- Cada base se inscribe por separado (art. 2.2.2.26.1.3). La información mínima incluye el responsable, los encargados, los canales para ejercer los derechos, el nombre y la finalidad de la base, la forma de tratamiento y la política (art. 2.2.2.26.2.1).
- La Circular Externa 3 de 2018 (numeral 2.1) agrega, entre otra información, las medidas de seguridad, el origen de los datos y las **transmisiones y transferencias internacionales** con el destinatario, su país y si hay contrato de transmisión.
- Una base creada después de los plazos de 2018-2019 se inscribe dentro de los dos meses siguientes a su creación (art. 2.2.2.26.3.1).

Aplicación a Insumap:

- La obligación es del **responsable**, es decir, de cada clínica, si cumple el umbral de activos. Una clínica pequeña puede quedar fuera. El valor en pesos de 100.000 UVT para 2026 es **pendiente de verificar**.
- Insumap, mientras sea académica y con datos simulados, no tiene obligación de inscribir una base real. Propuesta: la documentación de despliegue entrega a cada clínica la ficha técnica que necesita para su inscripción (finalidad, encargados, medidas de seguridad, transmisiones internacionales).
- Encargados y responsables no obligados a registrar reportan los incidentes por el aplicativo de la SIC (sección 16).

### 7.4 Responsabilidad demostrada y privacidad desde el diseño

Verificado:

- El responsable debe poder demostrar a la SIC que aplicó medidas apropiadas y efectivas, proporcionales a su naturaleza, a los datos, al tipo de tratamiento y a los riesgos (Decreto 1377, art. 26). Las políticas internas deben incluir una estructura administrativa, mecanismos como entrenamiento y procesos para atender consultas y reclamos (art. 27).
- La Resolución 866 de 2021 pide a los actores de la interoperabilidad un Programa Integral de Gestión de Datos Personales y seguir la guía de responsabilidad demostrada de la SIC (art. 17), aplicar privacidad desde el diseño y por defecto en todo el ciclo de vida del software (art. 18) y evaluar periódicamente el riesgo de seguridad digital (art. 19). La guía de la SIC no se abrió y es **pendiente de verificar**.

Cómo lo respalda Insumap:

- El modelo de amenazas, la minimización hacia la IA, la auditoría y las pruebas de seguridad de [`Seguridad.md`](Seguridad.md) son la evidencia técnica que la clínica puede mostrar.
- La lista de verificación por PR ([`Seguridad.md`](Seguridad.md), sección 19) vuelve la privacidad desde el diseño un paso de cada cambio.

## 8. Historia clínica

### 8.1 Resolución 1995 de 1999 (verificado)

- La historia clínica es "un documento privado, obligatorio y sometido a reserva" que solo puede ser conocido por terceros con autorización del paciente o en los casos previstos por la ley (art. 1 literal a).
- Aplica a todos los prestadores de servicios de salud y demás personas naturales o jurídicas que se relacionen con la atención en salud (art. 2).
- Características: integralidad, secuencialidad, racionalidad científica, disponibilidad y oportunidad (art. 3).
- Contenido mínimo de identificación: nombres, documento de identidad, fecha de nacimiento, dirección y teléfono, entre otros (art. 9). La identificación usa el número del documento (art. 6).
- La custodia está a cargo del prestador que la generó (art. 13). Acceden el usuario, el equipo de salud, las autoridades en los casos de ley y las demás personas que la ley determine (art. 14), y solo para fines legales, con reserva (art. 14, parágrafo).
- Archivo restringido, con acceso limitado a personal autorizado y sin adulteración (art. 16).
- Los programas automatizados deben tener mecanismos de seguridad que impidan modificar la historia una vez registrada y guardada; deben proteger la reserva e identificar al responsable de cada dato con su fecha y hora (art. 18).

### 8.2 Conservación: qué regla manda

| Norma | Regla | Estado |
|---|---|---|
| Resolución 1995 de 1999, art. 15 (texto original) | Mínimo **20 años** desde la última atención: 5 en archivo de gestión y 15 en archivo central. Después puede destruirse | Verificado. **Modificada** |
| Resolución 839 de 2017, art. 3 | Mínimo **15 años** desde la última atención: 5 en archivo de gestión y 10 en archivo central. Se duplica para víctimas de violaciones de derechos humanos o infracciones graves al derecho internacional humanitario. Es permanente si la historia forma parte de un proceso por delitos de lesa humanidad | Verificado |

La Resolución 839, art. 14, dice que "modifica en lo pertinente la Resolución número 1995 de 1999" sin listar artículos. Como el art. 3 de la 839 regula el mismo asunto del art. 15 de la 1995 con otro plazo, **la regla vigente es la de 15 años** de la Resolución 839. Que esa sea la lectura correcta es una **interpretación**; un abogado debe confirmarla. Hasta entonces el plazo es un parámetro de `audit.retention_policies`, no una cifra fija en el código.

La Ley 2015 de 2020, art. 3, añade que el Archivo General de la Nación reglamenta los tiempos de retención documental de las historias clínicas.

### 8.3 Historia clínica electrónica interoperable

Verificado:

- **Ley 2015 de 2020:** los prestadores deben disponer los datos de la historia clínica en la plataforma de interoperabilidad del Gobierno (art. 3). La persona es titular de su historia clínica electrónica y los sujetos obligados acceden con su consentimiento previo y expreso (art. 6). Solo el titular autoriza el uso por terceros, salvo los casos en que la ley no lo exige (art. 7).
- **Contenido y correcciones:** la información "no podrá ser modificada sin que quede registrada la modificación", incluso para corregir un error. La corrección agrega el dato nuevo con fecha, hora, nombre e identificación de quien corrige, "sin suprimir lo corregido" (art. 8, parágrafo 1).
- **Gratuidad:** el paciente tiene derecho a recibir su historia por medio electrónico, gratis, completa y rápida (art. 9).
- **Divulgación:** prohibida la divulgación de los datos por quien tuvo acceso (art. 12). Para profesionales y servidores públicos es falta gravísima (art. 12, parágrafo 1). Las EPS e IPS no pueden divulgar los datos que administran sin autorización expresa (art. 12, parágrafo 2).
- **Seguridad:** plan de seguridad y privacidad de la información, evaluación periódica del riesgo de seguridad digital y continuidad del servicio (art. 13).
- **Resolución 866 de 2021:** reglamenta el conjunto de datos clínicos relevantes para la interoperabilidad. Los datos no pueden comercializarse ni usarse para algo distinto a la atención en salud (art. 22). Los actores deben disponer los datos de las atenciones a través del mecanismo de interoperabilidad "una vez esté disponible" (art. 10) y tienen seis meses para integrarlos desde que se disponga el mecanismo (art. 26).
- La Resolución 866 no menciona FHIR ni HL7; remite al Lenguaje Común de Intercambio de MinTIC. Insumap usa FHIR R4 para importar y exportar ([`Datos-simulados.md`](Datos-simulados.md)); esto es una decisión técnica propia, no una exigencia de la resolución.

### 8.4 Qué significa para Insumap

1. La **historia clínica oficial es de la clínica** (custodia del prestador, Resolución 1995, art. 13). Insumap guarda los registros de monitoreo y las decisiones sobre las recomendaciones. Si el médico los incorpora al acto de atención, hacen parte de la historia clínica (interpretación). Por prudencia, Insumap trata **todos los datos H como si lo fueran** para la retención y la reserva.
2. **Append-only con correcciones.** Los datos clínicos no se borran ni se editan; se corrigen con una fila nueva ([`AGENTS.md`](../AGENTS.md), sección 5.2, regla 7). Esto coincide con la Ley 2015, art. 8, parágrafo 1, y con la Resolución 1995, art. 18.
3. **Identificación de quien registra.** `audit.audit_log` y `audit.data_access_log` guardan quién, qué y cuándo ([`Seguridad.md`](Seguridad.md), sección 7), lo que respalda la Resolución 1995, art. 18, último inciso.
4. **El número de documento** es un dato que la historia clínica debe llevar (Resolución 1995, arts. 6 y 9). Insumap lo guarda cifrado y solo lo descifra para exportar los datos del paciente o devolverlos a la clínica ([`Seguridad.md`](Seguridad.md), sección 8.1).
5. **Reserva.** El acceso se limita al paciente y a su equipo de atención, con un `404` ante cualquier otro intento ([`Seguridad.md`](Seguridad.md), secciones 6.3 y 6.5).
6. **Interoperabilidad.** Insumap no es la plataforma nacional de interoperabilidad. Conectarse a ella es una obligación de la clínica como prestador. Insumap no la implementa en el alcance actual (pendiente de verificar si el mecanismo nacional ya está disponible).

## 9. Telesalud y telemedicina

### 9.1 Qué dicen las normas (verificado)

- **Ley 1419 de 2010, art. 2:** telesalud es el conjunto de actividades de salud a distancia con TIC; telemedicina es la provisión de servicios de salud a distancia por profesionales de la salud que usan TIC para intercambiar datos.
- **Resolución 2654 de 2019:**
  - Aplica, entre otros, a los prestadores de servicios de salud y a las EPS (art. 2).
  - **Telemonitoreo** (art. 18): relación entre el personal de salud de un prestador y un usuario, "a través de una infraestructura tecnológica que recopila y trasmite a distancia datos clínicos, para que el prestador realice seguimiento y revisión clínica". Si el usuario se compromete a recoger y enviar los datos, su contenido es de su responsabilidad y el profesional verifica que esté entrenado.
  - **Consentimiento informado** (art. 7): cómo funciona la atención con TIC, alcance, riesgos, manejo de privacidad y de datos personales, qué hacer en emergencias y ante fallas tecnológicas. Se deja constancia en la historia clínica.
  - **Plataformas** (art. 21): las aplicaciones web y móviles, entre otras, pueden ser del prestador o de un tercero y "estarán bajo la responsabilidad de quien brinda el servicio de salud".
  - **Seguridad** (art. 22): los prestadores garantizan autenticidad, integridad, disponibilidad y fiabilidad; la plataforma controla permisos de acceso, y usa certificados y cifrado (22.2); y cuando la plataforma es de un tercero, el prestador verifica sus condiciones de seguridad, privacidad y confidencialidad (22.4).
  - **Habeas data** (art. 24): quienes participan en el flujo de la información responden por el régimen de protección de datos y, cuando aplique, inscriben las bases en el RNBD.
  - **Proveedor tecnológico** (art. 3): persona jurídica que proporciona servicios relacionados con TIC.

### 9.2 Aplicación (interpretación)

- Insumap se parece a una **plataforma de telemonitoreo**: el paciente registra datos y el médico los revisa a distancia. Si una clínica la usa así, el servicio de salud es de la clínica y la plataforma queda bajo su responsabilidad (art. 21). Insumap sería su **proveedor tecnológico**, no un prestador de servicios de salud.
- La clínica debe poder **verificar** la seguridad de Insumap (art. 22.4). Por eso [`Seguridad.md`](Seguridad.md) es un documento que la clínica puede entregar a su área de seguridad.
- La habilitación del servicio de telemedicina es de la clínica en el Sistema Único de Habilitación (Resolución 2654, art. 1, parágrafo). No es un trámite de Insumap.
- El **consentimiento de telesalud** (art. 7) queda en la historia clínica de la clínica. El consentimiento de Insumap (sección 14) es del tratamiento de datos en la app y no lo reemplaza. Propuesta: el aviso de la app indique que la clínica puede pedir además su propio consentimiento de telesalud.
- Insumap no ofrece teleconsulta en video ni prescripción. La mensajería médico-paciente ([`Requerimientos.md`](Requerimientos.md), módulo M11) queda como mensajería de seguimiento. Si una clínica la usara como consulta, la Resolución 2654 aplica a la clínica.

## 10. Dispositivos médicos y software

### 10.1 Qué dice el Decreto 4725 de 2005 (verificado)

- Art. 2: dispositivo médico para uso humano es "cualquier instrumento, aparato, máquina, **software**, equipo biomédico u otro artículo similar o relacionado, utilizado sólo o en combinación, incluyendo sus componentes, partes, accesorios y programas informáticos que intervengan en su correcta aplicación, **propuesta por el fabricante** para su uso en: a) Diagnóstico, prevención, supervisión, tratamiento o alivio de una enfermedad" (y otros usos).
- Art. 5: la clasificación por riesgo va de la clase I a la III, con las reglas del art. 7. La regla 10 cubre los dispositivos activos con fines de diagnóstico, incluida la vigilancia de procesos fisiológicos vitales.
- Arts. 16 y 17: los dispositivos y equipos que no son de tecnología controlada requieren registro sanitario (clases IIb y III) o registro sanitario automático (clases I y IIa) del INVIMA para su "producción, importación, exportación, procesamiento, envase, empaque, almacenamiento, expendio y comercialización".

### 10.2 Aplicación (interpretación, no conclusión)

**No se afirma que Insumap quede fuera de la definición.** El art. 2 incluye software y mira el uso que **propone el fabricante**, entre ellos la "supervisión" de una enfermedad. Funcionalmente, el monitoreo de glucosa, el triage, las alertas y las propuestas de titulación de IA4 se acercan a ese terreno. La clase de riesgo que le correspondería (por ejemplo, la regla 10) y la posición del INVIMA sobre software son **pendientes de verificar**. Una fuente secundaria menciona una posición del INVIMA de 2026 sobre dispositivos vestibles; no se verificó y no se usa.

Lo que sí es verificable es lo que Insumap hace para mantenerse en el terreno académico:

| Medida | Dónde |
|---|---|
| El uso propuesto es académico: demostrar patrones de diseño e IA de apoyo, no tratar pacientes | [`AGENTS.md`](../AGENTS.md), sección 1 |
| Datos 100 % simulados y la clínica demo marcada "Datos simulados" (RF-96) | [`Datos-simulados.md`](Datos-simulados.md) |
| No se comercializa, no se importa ni se produce para venta. Los arts. 16 y 17 atan el registro a esas actividades | Este documento |
| El médico decide: la IA propone y el médico aprueba, modifica o rechaza con motivo (P13). La IA nunca da dosis al paciente | [`Modulo-IA.md`](Modulo-IA.md), [`Contrato-IA.md`](Contrato-IA.md) |
| Aviso fijo en la UI, los reportes y la documentación: no es un dispositivo médico | [`Riesgos.md`](Riesgos.md), RG-05 |
| Los resultados con datos simulados prueban el sistema, no su eficacia clínica | [`Datos-simulados.md`](Datos-simulados.md) |

Advertencia: el aviso "no es un dispositivo médico" **no basta por sí solo**. Lo que cuenta es el uso que se proponga y se promocione. Propuesta de reglas de contenido:

1. Ningún texto de la UI, del README ni de la demo afirma que Insumap diagnostica, trata o previene una enfermedad.
2. Las salidas de la IA se presentan como "apoyo para el médico", con su explicación y versión de modelo.
3. Antes de cualquier uso clínico real, se pide un concepto jurídico y regulatorio sobre la clasificación y el registro ante el INVIMA.

## 11. Transferencias y transmisiones internacionales

Esta sección es la que [`Stack-tecnologico.md`](Stack-tecnologico.md) cita para los datos que quedan fuera de Colombia.

### 11.1 Conceptos (verificado)

| Concepto | Definición | Fuente |
|---|---|---|
| **Transferencia** | El responsable o encargado ubicado en Colombia envía los datos a un receptor que **a su vez es responsable** del tratamiento, dentro o fuera del país | Decreto 1377, art. 3 numeral 4 |
| **Transmisión** | Comunicación de datos dentro o fuera del país para que un **encargado** los trate **por cuenta del responsable** | Decreto 1377, art. 3 numeral 5 |
| **Regla para transferencias** | Se prohíben a países sin nivel adecuado de protección, salvo seis excepciones: (a) autorización expresa e inequívoca del titular; (b) intercambio de datos médicos por razones de salud o higiene pública cuando lo exija el tratamiento del titular; (c) transferencias bancarias o bursátiles; (d) tratados con reciprocidad; (e) ejecución de un contrato con el titular, con su autorización; (f) interés público o defensa de un derecho en un proceso judicial. Fuera de esos casos, la SIC emite una declaración de conformidad (parágrafo 1) | Ley 1581, art. 26 |
| **Regla para transmisiones** | No hay que informarlas al titular ni pedirle consentimiento **si existe un contrato** entre responsable y encargado | Decreto 1377, art. 24 numeral 2; Decreto 1074, art. 2.2.2.25.5.1 |
| **Contenido del contrato** | Alcance, actividades del encargado y obligaciones: aplicar la política, tratar los datos según la finalidad autorizada, proteger su seguridad y confidencialidad | Decreto 1377, art. 25; Decreto 1074, art. 2.2.2.25.5.2 |
| **País adecuado** | El que cumple los estándares fijados por la SIC, nunca inferiores a los de la Ley 1581 | Ley 1581, art. 26 |

### 11.2 Lista de países de la SIC y Estados Unidos

- La Circular Externa 5 de 2017 incorporó al Capítulo Tercero del Título V la lista de países adecuados. El numeral 3.2, según la Circular Externa 8 de 2017 (la copia leída), incluye **"Estados Unidos de América"**, entre otros, y los países que la Comisión Europea haya declarado adecuados. La SIC "ejercerá, en cualquier tiempo, su capacidad regulatoria para revisar la lista" (verificado).
- La SIC publicó la Circular Externa 2 de 2025 sobre transferencia de tecnología con datos personales. El concepto de la SIC que la comenta indica que reitera los estándares para identificar países adecuados y la vía de la declaración de conformidad (verificado en el resumen del boletín). El texto de la circular es un PDF escaneado que no se pudo leer.
- **Pendiente de verificar:** si el numeral 3.2 sigue vigente hoy con Estados Unidos en la lista, y la fecha exacta de la Circular Externa 2 de 2025. Hasta confirmarlo, el diseño no se apoya en la lista.

### 11.3 Aplicación a la infraestructura de Insumap

| Proveedor | Qué recibe | Calificación (interpretación) | Estado |
|---|---|---|---|
| **Neon** (PostgreSQL) | Todos los datos del sistema, incluidos H y C | Transmisión al encargado Insumap y a su subencargado, bajo contrato | Región y contrato (DPA) pendientes de verificar |
| **Render** (API y servicio de IA) | Datos H y C en tránsito y en memoria; logs sin datos personales ([`Seguridad.md`](Seguridad.md), sección 11) | Transmisión a un subencargado | Región y contrato pendientes de verificar |
| **Vercel** (frontend estático) | El build estático. No guarda datos de pacientes; sus registros de acceso pueden incluir direcciones IP | Transmisión a un subencargado, de bajo riesgo | Si sus términos exigen un uso no comercial: pendiente (ver [`Stack-tecnologico.md`](Stack-tecnologico.md), sección 8.1, punto 6) |
| **Proveedor de correo** | Correo del paciente y el enlace de la invitación, sin datos clínicos | Transmisión a un subencargado | Proveedor sin elegir |
| **Proveedor del LLM** (IA5 e IA6) | Datos seudonimizados y texto redactado ([`Seguridad.md`](Seguridad.md), sección 9) | Ver 11.4 | Proveedor y país sin elegir (Fase 10) |

Reglas de diseño (propuestas):

1. La clínica firma con Insumap el contrato de transmisión del Decreto 1377, art. 25. Insumap traslada las mismas obligaciones a cada subencargado por contrato. Que la norma no regule esa cadena es **pendiente de verificar**; por eso se cubre por contrato.
2. Antes de un piloto real, se confirman la región de Render y de Neon y se firman sus términos de procesamiento de datos.
3. La clínica declara, en su ficha de RNBD, la transmisión internacional con el país del encargado (Circular Externa 3 de 2018, numeral 2.1).
4. Se prefiere una región de Estados Unidos o de la Unión Europea, por la lista de la SIC de 2017, mientras su vigencia no se haya confirmado de nuevo.
5. El cifrado en tránsito y en reposo, las llaves fuera de los respaldos y el aislamiento por clínica ([`Seguridad.md`](Seguridad.md), secciones 8, 13.2 y 16) reducen el riesgo de la salida de los datos.

### 11.4 El LLM externo: transmisión o transferencia (interpretación)

- Si el proveedor del LLM solo procesa los datos **por cuenta de Insumap** y **no los usa para sus propios fines** (ni para entrenar), es un encargado y el envío es una **transmisión**.
- Si el proveedor usa los datos para **sus propios fines**, pasa a ser **responsable**, y el envío sería una **transferencia** sujeta al art. 26 de la Ley 1581.
- Un seudónimo `sub_...` no vuelve anónimos los datos para Insumap, que conserva la llave HMAC y puede reidentificar. El texto libre puede contener identificadores. Por eso se tratan como datos personales sensibles (interpretación; la ley define el dato personal como el que "pueda asociarse" a una persona, art. 3 literal c).

Esto fundamenta tres controles de [`Seguridad.md`](Seguridad.md), sección 9:

| Control | Base |
|---|---|
| `LLM_REAL_DATA_ALLOWED=false` por defecto. Solo se activa con un proveedor que **excluya por contrato el entrenamiento** con los datos, y con la base legal de esta sección | Evita que el proveedor sea responsable y que el envío sea una transferencia sin base |
| `ai_external_processing` como consentimiento **aparte, opcional y expreso** | Si una transferencia llegara a ocurrir, la autorización expresa e inequívoca del titular es la excepción del art. 26 literal a |
| Sin consentimiento, el asistente usa respuestas predefinidas | El paciente no pierde el servicio por negarse (coherente con la sección 5.2) |

## 12. Menores de edad

Verificado:

- El tratamiento de datos de niños, niñas y adolescentes está proscrito salvo los de naturaleza pública, y debe respetar sus derechos prevalentes (Ley 1581, art. 7).
- El Decreto 1377, art. 12, lo permite si responde al interés superior del menor y respeta sus derechos fundamentales. Entonces el **representante legal** otorga la autorización, "previo ejercicio del menor de su derecho a ser escuchado", valorada según su madurez, autonomía y capacidad.
- Es facultativa la respuesta sobre datos de menores (Ley 1581, art. 12 literal b).
- La Resolución 1995, art. 6, identifica a los menores con tarjeta de identidad o registro civil, y con el documento del padre o la madre cuando no existe el propio.

La interpretación de la Ley 1581, art. 7, frente a la Sentencia C-748 de 2011 de la Corte Constitucional no se verificó y es **pendiente de verificar**.

Decisión (propuesta) para cerrar el pendiente de [`Seguridad.md`](Seguridad.md), sección 20:

1. **Mientras no exista un flujo de representación legal, no se importan ni activan cuentas de pacientes menores reales.** Basta calcular la edad con `birth_date` en la importación y rechazar la activación de menores de 18 años con un error claro (código por definir en `ErrorCode`).
2. Los perfiles simulados `t1d_adolescent` y similares sí se permiten, porque no son personas reales ([`Datos-simulados.md`](Datos-simulados.md)).
3. Un flujo futuro necesitaría: cuenta de representante, autorización del representante con la escucha del menor, versión del aviso para menores y un cambio de estado al cumplir la mayoría de edad. Queda fuera del alcance actual.

## 13. Mapa de obligaciones a controles

Cada fila enlaza la obligación con el control de Insumap. Las secciones de `Seguridad.md` describen el cómo.

| # | Obligación | Fuente verificada | Control en Insumap | Dónde |
|---|---|---|---|---|
| 1 | Tratar datos sensibles solo con autorización explícita | Ley 1581, arts. 5 y 6 | Consentimiento versionado, alcance `sensitive_data_processing` (propuesta), `403 CONSENT_REQUIRED` en la activación | `Seguridad.md` 3.4; sección 14 |
| 2 | Informar finalidad, carácter facultativo, derechos y responsable al pedir la autorización | Ley 1581, art. 12; Decreto 1377, arts. 6 y 15 | Aviso de privacidad versionado de la clínica, mostrado antes del consentimiento | `Seguridad.md` 3.4; sección 14.3 |
| 3 | Conservar prueba de la autorización | Decreto 1377, art. 8; Ley 1581, art. 12 parágrafo | `clinic.patient_consents` con versión, fecha, alcance e `ip_hmac`. Append-only: el retiro es una fila nueva | `Seguridad.md` 3.4; sección 14.2 |
| 4 | Finalidad limitada; nueva autorización si cambia la finalidad | Ley 1581, art. 4 literal b; Decreto 1377, art. 5 | Una versión nueva del aviso obliga a reaceptar (`409 CONSENT_VERSION_OUTDATED`); el alcance de IA externa es un consentimiento aparte | `Seguridad.md` 2.6 y 3.4 |
| 5 | Recolectar solo datos pertinentes y adecuados | Decreto 1377, art. 4 | Entradas con `extra="forbid"` y `FieldLimits`; la importación toma solo los campos del esquema | `AGENTS.md` 3.3; `Seguridad.md` 13.3 |
| 6 | Minimizar hacia terceros | Ley 1581, art. 4 literales b y f; Resolución 866, art. 18 | Solo un seudónimo llega a `insumap-ai` y al LLM; texto libre redactado dos veces | `Seguridad.md` 9 |
| 7 | Acceso y circulación restringida; reserva de la historia clínica | Ley 1581, art. 4 literal f; Resolución 1995, arts. 1 y 14 | RLS por clínica, `PatientRecordAccessProxy` (P11), `404` ante lo no asignado | `Seguridad.md` 6 |
| 8 | Seguridad contra adulteración, pérdida y acceso no autorizado | Ley 1581, arts. 17 literal d y 18 literal b; Resolución 2654, art. 22 | Argon2id, JWT, MFA del personal, cifrado, cabeceras, límites de tasa, CI con Gitleaks y CodeQL | `Seguridad.md` 2 a 5, 8, 12 a 15 |
| 9 | Registrar quién accedió a la historia | Resolución 1995, art. 18 | `audit.data_access_log` por cada lectura H, con fallo cerrado; `audit.audit_log` con cadena de hashes | `Seguridad.md` 7 |
| 10 | No modificar la historia; corregir con un dato nuevo | Resolución 1995, art. 18; Ley 2015, art. 8 parágrafo 1 | Datos clínicos append-only con correcciones; triggers que rechazan `UPDATE` y `DELETE` | `AGENTS.md` 5.2; `Seguridad.md` 7 |
| 11 | Número de documento como dato de identificación | Resolución 1995, arts. 6 y 9 | `document_ciphertext` (AES-256-GCM), `document_hash` (HMAC) y `document_last4`; descifrado auditado | `Seguridad.md` 8.1 |
| 12 | Atender consultas (10 días hábiles) y reclamos (15 días hábiles) | Ley 1581, arts. 14 y 15 | Solicitudes del titular con estado y plazo en parámetros de BD (RF-93, HU-53); exportación JSON y FHIR | Sección 6 |
| 13 | Revocar la autorización | Ley 1581, art. 8 literal e; Decreto 1377, art. 9 | Retiro del consentimiento (RF-90, HU-52): se detienen nuevos registros y la clínica recibe un aviso | Sección 14.4 |
| 14 | Limitar la conservación al tiempo necesario, salvo deber legal | Decreto 1377, art. 11 | `audit.retention_policies` por tipo de dato; purgas con `PURGE` en `audit_log` | `Seguridad.md` 16; sección 15 |
| 15 | Conservar la historia clínica mínimo 15 años desde la última atención | Resolución 839 de 2017, art. 3 | Los datos H no se purgan antes del plazo; el paciente desactivado conserva su historia (RF-94) | Sección 15 |
| 16 | Informar a la SIC las violaciones a los códigos de seguridad | Ley 1581, arts. 17 literal n y 18 literal k; Circular Externa 3 de 2018 | Procedimiento de incidentes con severidades y evidencia | `Seguridad.md` 17; sección 16 |
| 17 | Contrato de transmisión con el encargado | Decreto 1377, arts. 24 y 25 | Contrato clínica-Insumap y traslado a subencargados | Sección 11.3 |
| 18 | Transferencia internacional solo con base legal | Ley 1581, art. 26 | `LLM_REAL_DATA_ALLOWED=false`; `ai_external_processing` aparte; solo datos simulados en la capa gratuita | `Seguridad.md` 9; sección 11.4 |
| 19 | Responsabilidad demostrada y privacidad desde el diseño | Decreto 1377, arts. 26 y 27; Resolución 866, arts. 17 a 19 | Modelo de amenazas, pruebas de seguridad y lista de verificación por PR | `Seguridad.md` 1, 18 y 19 |
| 20 | Designar a quien atienda a los titulares | Decreto 1377, art. 23 | Contacto de privacidad de la clínica y de Insumap (por designar) | Sección 4.2 |
| 21 | Responsabilidad de la plataforma de telemonitoreo | Resolución 2654, arts. 18, 21 y 22 | Insumap como proveedor tecnológico; `Seguridad.md` como evidencia para la clínica | Sección 9 |
| 22 | Datos de menores solo con representante legal | Ley 1581, art. 7; Decreto 1377, art. 12 | No se activan menores reales sin flujo de representación | Sección 12 |
| 23 | No ser un dispositivo médico no registrado | Decreto 4725, arts. 2, 16 y 17 | Uso académico, datos simulados, sin comercialización, el médico decide, avisos | Sección 10 |
| 24 | Los datos de interoperabilidad no se comercializan ni se usan para otro fin | Resolución 866, art. 22 | Ningún uso comercial ni publicitario de los datos; la IA solo apoya la atención | Sección 14.1 |
| 25 | Marcar el origen simulado | Propuesta propia (RF-96) | `is_demo`, "Datos simulados" en la UI, reportes y API | `AGENTS.md` 3.5 |

## 14. Consentimiento y aviso de privacidad

Esta sección cierra los pendientes de [`Seguridad.md`](Seguridad.md), secciones 3.4, 9 y 21 (decisión 12).

### 14.1 Alcances (propuesta)

| Alcance | Obligatorio | Cubre | Sin él |
|---|---|---|---|
| `sensitive_data_processing` ("tratamiento de datos sensibles") | Sí, para usar la app (ver la lectura de la sección 5.2) | Registrar y tratar los datos de salud del paciente en Insumap con las finalidades del aviso: monitoreo por su equipo de atención, métricas, alertas, recomendaciones que aprueba el médico, mensajería de seguimiento y reportes | `403 CONSENT_REQUIRED`; la cuenta sigue `INVITED` |
| `ai_external_processing` | No | Enviar datos seudonimizados y texto redactado a un proveedor externo de LLM para el asistente (IA6) y los textos de IA5 | El asistente usa respuestas predefinidas; el resto de la app funciona igual |

Finalidades **no incluidas** en ningún alcance, y por tanto prohibidas sin una autorización nueva: publicidad, venta o cesión de datos, entrenamiento de modelos de terceros con datos reales, y cualquier uso que no sea la atención en salud (coherente con la Resolución 866, art. 22). La IA propia de Insumap (IA1 a IA4, IA7) corre en `insumap-ai`, sin estado y con seudónimo; usa los datos para apoyar la atención dentro de la finalidad de `sensitive_data_processing` (interpretación).

### 14.2 Registro del consentimiento (propuesta)

Cada fila de `clinic.patient_consents` guarda como mínimo:

| Campo | Para qué |
|---|---|
| `patient_id`, `clinic_id` | A quién y de qué clínica |
| `privacy_notice_version_id` | Qué texto exacto aceptó |
| `scope` | `sensitive_data_processing` o `ai_external_processing` |
| `status` | `GRANTED` o `WITHDRAWN` |
| `occurred_at` | Cuándo (hora del `Clock` inyectado) |
| `ip_hmac` | Evidencia sin guardar la IP en claro |

Es **append-only**: retirar el consentimiento agrega una fila `WITHDRAWN`, no borra la anterior. Así la clínica conserva la prueba exigida por el Decreto 1377, art. 8. Cada cambio de consentimiento escribe una fila en `audit.audit_log` ([`Seguridad.md`](Seguridad.md), sección 7.2). Los nombres exactos de columnas los fija `insumap-database` y [`Modelo-de-datos.md`](Modelo-de-datos.md).

### 14.3 Contenido mínimo del aviso de privacidad

Para cumplir la Ley 1581, art. 12, y el Decreto 1377, arts. 13 y 15, la plantilla del aviso incluye:

1. Identificación, dirección y contacto de la **clínica** como responsable, y mención de Insumap como encargada.
2. Los **datos** que se tratan (salud, identidad y contacto) y sus **finalidades** específicas, en lenguaje claro.
3. Que los datos de salud son **sensibles** y que **no está obligado a autorizar** su tratamiento, y que negarse **no afecta su atención** en la clínica (sección 5.2).
4. Que `ai_external_processing` es **opcional** y separado, con el país o la región del proveedor cuando se conozca.
5. Que sus datos pueden alojarse **fuera de Colombia** (sección 11).
6. Sus **derechos** (conocer, actualizar, rectificar, pedir prueba de la autorización, revocar, pedir supresión, quejarse ante la SIC) y cómo ejercerlos, con la persona o área de atención.
7. Cuánto se **conservan** los datos (sección 15), incluida la conservación de la historia clínica por deber legal.
8. Cómo consultar la política de tratamiento completa y sus **cambios sustanciales**.
9. La **versión** y la fecha del aviso.
10. El **aviso académico**: Insumap no es un dispositivo médico, la IA solo apoya al médico y los datos de la clínica demo son simulados.

El texto final lo redacta y aprueba la clínica con su asesor jurídico. Insumap entrega la plantilla y el mecanismo de versiones.

### 14.4 Versiones y retiro

- Una versión nueva del aviso obliga a reaceptar antes de seguir registrando (RF-90). Un cambio de finalidad exige una autorización nueva (Decreto 1377, art. 5).
- Retirar `sensitive_data_processing` detiene los nuevos registros y avisa a la clínica para que tramite la baja o la retención (HU-52). Retirar `ai_external_processing` solo desactiva el asistente con LLM externo.
- El retiro **no borra** lo ya registrado cuando hay un deber legal de conservarlo (Decreto 1377, art. 9; sección 15).

## 15. Retención y supresión

Cierra el pendiente de [`Seguridad.md`](Seguridad.md), sección 16. Esa sección fija las cifras de las tablas técnicas; aquí se fija el criterio para los datos clínicos y de cumplimiento.

| Dato | Criterio | Estado |
|---|---|---|
| Registros clínicos (H) y decisiones sobre recomendaciones | Mínimo **15 años desde la última atención** (Resolución 839 de 2017, art. 3), salvo las ampliaciones de ese artículo. La custodia legal es de la clínica; Insumap no purga antes de que la clínica lo pida y el plazo se cumpla | Verificado (plazo); propuesta (aplicación a Insumap) |
| Consentimientos | Se conservan mientras se traten los datos del paciente a los que se refieren, y mientras dure la conservación de su historia, para poder probar la autorización (Decreto 1377, art. 8). No se encontró un plazo legal propio | Propuesta; plazo legal pendiente de verificar |
| `audit.audit_log` y `audit.data_access_log` | Igual que los datos que auditan: no se purgan antes que ellos. No se encontró un plazo legal propio | Propuesta; plazo legal pendiente de verificar |
| Datos técnicos (`iam.login_attempts`, `security_events`, tokens) | Las cifras de [`Seguridad.md`](Seguridad.md), sección 16. Se justifican por el Decreto 1377, art. 11: conservar solo el tiempo razonable y necesario y documentar el procedimiento | Verificado (principio); propuesta (cifras) |
| Datos de la clínica demo | Sin plazo legal: son simulados y se pueden regenerar o borrar | Interpretación |

Reglas:

1. **Supresión.** El paciente puede pedirla, pero no procede mientras exista el deber de conservar la historia clínica (Decreto 1377, art. 9). La respuesta de la clínica lo explica y ofrece el retiro del consentimiento, que detiene nuevos registros.
2. **Fin del plazo.** Cumplido el plazo, los datos se **anonimizan** conservando estadísticas agregadas (RF-94) o se destruyen, previa decisión de la clínica. La Resolución 839, art. 3, ordena además publicar como mínimo dos avisos en un diario de amplia circulación nacional, con ocho días de intervalo, para ofrecer la entrega de la historia al usuario antes de la disposición final (verificado).
3. **Cierre de la clínica o del servicio.** Si Insumap deja de operar, devuelve los datos a la clínica y borra los suyos tras la devolución. La Resolución 839 regula la historia clínica de las entidades en liquidación o con cierre definitivo del servicio (art. 6) y la continuidad cuando otro prestador asume la sede (art. 10); es una obligación de la clínica, no de Insumap.
4. Toda purga escribe `PURGE` en `audit.audit_log` antes de borrar, y todo cambio de retención escribe `RETENTION_POLICY_CHANGED` ([`Seguridad.md`](Seguridad.md), sección 16).

## 16. Incidentes y brechas

Cierra el pendiente de [`Seguridad.md`](Seguridad.md), sección 17, pasos 6 y 8.

### 16.1 Qué es obligatorio (verificado)

- El **responsable** informa a la autoridad de protección de datos cuando hay "violaciones a los códigos de seguridad" y riesgos en la administración de la información de los titulares (Ley 1581, art. 17 literal n).
- El **encargado** informa a la SIC en los mismos términos (art. 18 literal k).
- **Plazo y canal** (Circular Externa 3 de 2018, numeral 2.1 literal f): un incidente de seguridad es la "violación de los códigos de seguridad o la pérdida, robo y/o acceso no autorizado de información de una base de datos". Se reporta en **15 días hábiles** desde que se detecta y se pone en conocimiento de la persona o área encargada de atenderlo. Los responsables obligados al RNBD lo reportan al RNBD. Los responsables no obligados y los encargados lo reportan por el aplicativo de la SIC o por sus canales habilitados, en el mismo plazo.
- La vigencia de la circular después de su fecha es **pendiente de verificar**.

### 16.2 Qué no se encontró

- Una norma que obligue a **notificar a los titulares** una brecha, en general, **no se encontró** en los textos leídos. Es **pendiente de verificar**. Mientras tanto, se propone informarles de forma proporcionada cuando haya riesgo para ellos, a través de la clínica.
- Un plazo para que el encargado avise al responsable **no se encontró**. El objetivo de 24 horas de [`Seguridad.md`](Seguridad.md), sección 17, es una propuesta interna.

### 16.3 Procedimiento (propuesta)

| Paso | Acción | Responsable |
|---|---|---|
| 1 | Detectar y registrar la hora de detección (la que cuenta para el plazo) | Insumap |
| 2 | Contener y evaluar con `data_access_log` y `security_events` ([`Seguridad.md`](Seguridad.md), sección 17) | Insumap |
| 3 | Avisar a la clínica afectada, objetivo interno de 24 horas desde la confirmación, con las clases de datos y los pacientes afectados | Insumap |
| 4 | Reportar a la SIC dentro de **15 días hábiles** desde la detección, por el canal que corresponda (RNBD o aplicativo) | La clínica como responsable; Insumap como encargada, por el aplicativo, en su propio caso |
| 5 | Evaluar con la clínica la comunicación a los titulares afectados | La clínica |
| 6 | Informe sin culpables en `docs/incidentes/` y acciones en la lista de verificación | Insumap |

Para evitar el doble reporte, el contrato clínica-Insumap fija quién reporta y que ambas partes se pasan el número de radicado de la SIC.

## 17. Pendientes y no verificado

| Tema | Qué falta |
|---|---|
| Vigencia de la lista de países de la SIC | Confirmar si el numeral 3.2 sigue vigente con Estados Unidos, y leer la Circular Externa 2 de 2025 (PDF escaneado) |
| Sentencia C-748 de 2011 | Leer qué dijo sobre el art. 7 (menores) y sobre el art. 26 (transferencias) |
| Guía de la SIC sobre responsabilidad demostrada y guías de la SIC sobre nube | No se abrieron |
| Cadena de subencargados | La norma leída regula solo responsable y encargado. Confirmar con un abogado |
| Regiones y contratos de Render, Neon, Vercel, correo y LLM | Confirmar región y términos de procesamiento antes de un piloto |
| Notificación a los titulares por una brecha | No se encontró obligación general |
| Plazo legal de retención de consentimientos y de auditoría | No se encontró |
| Valor de 100.000 UVT en 2026 | Confirmar para saber qué clínicas deben inscribirse en el RNBD |
| Modificaciones posteriores de las normas | Los normogramas pueden ir por detrás del Diario Oficial: confirmar la vigencia |
| Clasificación de riesgo y posición del INVIMA sobre software | Pedir un concepto regulatorio antes de cualquier uso clínico |
| Plataforma nacional de interoperabilidad | Confirmar si el mecanismo de la Resolución 866 ya está disponible |
| Plantilla de contrato de transmisión | Redactarla con un abogado (modelo según Decreto 1377, art. 25) |
| Rango de teléfonos ficticios de [`Datos-simulados.md`](Datos-simulados.md), sección 3.1 | Está pendiente de esta verificación y **no se cierra aquí**: no se abrió ninguna fuente sobre numeración telefónica. Se mantiene "pendiente de verificar" |
| Normas no incluidas | Ley 23 de 1981 (ética médica) y Ley 1751 de 2015 (derecho a la salud) se mencionan dentro de otras normas pero no se leyeron |

## 18. Qué cierra este documento en otros documentos

| Origen | Pendiente | Dónde se cierra |
|---|---|---|
| [`Seguridad.md`](Seguridad.md), 3.4 | Texto y base legal del consentimiento | Secciones 5 y 14 |
| [`Seguridad.md`](Seguridad.md), 9 | Base legal de la transferencia al LLM y del `ai_external_processing` | Sección 11.4 |
| [`Seguridad.md`](Seguridad.md), 16 | Retención de datos clínicos, de consentimientos y de auditoría | Sección 15 |
| [`Seguridad.md`](Seguridad.md), 17 | Procedimiento, plazos y canal de notificación a la SIC y a los titulares | Sección 16 |
| [`Seguridad.md`](Seguridad.md), 20 | Cuentas de menores de edad y representación legal | Sección 12 |
| [`Seguridad.md`](Seguridad.md), 21 (decisión 12) | Alcances de consentimiento | Sección 14.1 |
| [`Insumap.md`](Insumap.md) | Matices de responsable y encargado | Sección 4 |
| [`Stack-tecnologico.md`](Stack-tecnologico.md), 8.1 punto 5 | Datos fuera de Colombia | Sección 11 |
| [`Datos-simulados.md`](Datos-simulados.md), 3.1 | Rango de teléfonos ficticios | Sigue pendiente (sección 17) |
| [`Riesgos.md`](Riesgos.md), RG-05 | Fuentes legales verificadas | Sección 3 |
| [`Arquitectura.md`](Arquitectura.md) | Conservación de la historia clínica (Resolución 1995) | Sección 8.2: la regla vigente es la Resolución 839 de 2017, art. 3 |
