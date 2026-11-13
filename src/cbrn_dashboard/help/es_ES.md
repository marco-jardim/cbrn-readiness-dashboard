# Ayuda

## Visión general
<!-- topic: overview -->

Este programa registra y evalúa los datos de preparación de un comité: personal, infraestructura, ejercicios y presupuesto. Todos los datos se guardan en una única base de datos en este equipo. El programa no tiene acceso a la red.

La ventana tiene la lista de páginas a la izquierda, una barra de herramientas con la fecha de referencia, avisos en la parte superior y una barra de estado en la parte inferior. La barra de estado muestra los recuentos de alertas de la fecha de referencia, cuando se pueden leer, y la carpeta de datos. Los menús son Archivo (hacer copia de seguridad, restaurar, abrir la carpeta de datos, salir), Idioma y Ayuda.

En el modo de solo lectura un aviso lo indica y toda acción que modifica datos queda desactivada.

Esta guía solo explica cómo funciona el programa. No contiene contenido clínico ni de procedimientos.

## Fecha de referencia
<!-- topic: as_of -->

Todas las cifras de las páginas se calculan para la fecha de referencia que muestra la barra de herramientas. Al iniciar es la fecha de hoy y permanece fija hasta que usted la cambie, incluso después de la medianoche.

Elija otra fecha en el campo de fecha (tiene un calendario) para ver la situación de ese día, por ejemplo para consultar el pasado. El botón Hoy vuelve a la fecha actual.

Los indicadores, las alertas, el estado de los certificados y de los activos y la ejecución presupuestaria siguen la fecha de referencia. Cambiar la fecha de referencia nunca modifica los datos almacenados.

## Panel
<!-- topic: dashboard -->

El Panel muestra una ficha por cada indicador, agrupada por módulo: el valor, su unidad, el estado y los umbrales vigentes. El estado se escribe siempre en texto, junto con una forma y un color, para poder leerlo sin depender del color. "Sin meta" significa que no se ha definido ninguna meta para el indicador. "Sin datos" significa que no hay datos a partir de los cuales calcularlo. El programa no combina los indicadores en una nota global.

La página también muestra el número de alertas por gravedad y algunos gráficos. Cada gráfico tiene la opción "Mostrar como tabla", que muestra los mismos números en una tabla.

"Registrar instantánea" guarda las lecturas de la fecha de referencia (véase Instantáneas). Modifica datos, por lo que queda desactivada en el modo de solo lectura.

## Personal
<!-- topic: personnel -->

La página Personal enumera al personal con filtros, muestra el estado de cada persona por nivel de certificado de EPI en la fecha de referencia y cuenta las personas por nivel. Seleccione una persona para ver los certificados, los registros de formación y los títulos académicos.

Las personas se identifican con un código interno y una etiqueta corta opcional. No escriba números de documentos de identidad ni otros datos personales: el programa rechaza un identificador que parezca un número de documento de identidad.

Se pueden añadir, editar, desactivar y eliminar personas, y añadir, editar y eliminar certificados, registros de formación y títulos. "Definir sin renovación" marca que no se espera la renovación de un certificado, y "Quitar sin renovación" deshace la marca. "Seudonimizar persona" sustituye el identificador y el texto libre por códigos aleatorios y no se puede deshacer. Eliminar a una persona también elimina sus certificados, registros de formación y títulos. Eliminar y seudonimizar piden confirmación antes.

La lista de cursos de formación se mantiene en Ajustes.

## Infraestructura
<!-- topic: infrastructure -->

La página Infraestructura enumera los activos por tipo y etiqueta con su estado en la fecha de referencia, el último mantenimiento y la próxima fecha prevista. Indicaciones escritas en texto muestran el mantenimiento vencido, el mantenimiento próximo a vencer y los activos cuyo calendario de mantenimiento se desconoce. La página también muestra la disponibilidad por tipo y el historial del activo seleccionado.

Se pueden añadir, editar, dar de baja y eliminar activos, cambiar el estado de un activo, registrar un mantenimiento y editar o eliminar entradas del historial.

Los tipos de activo y la regla de disponibilidad, que decide si las unidades degradadas cuentan como disponibles, se mantienen en Ajustes.

## Ejercicios
<!-- topic: exercises -->

La página Ejercicios enumera las ediciones de ejercicios, que se pueden filtrar por tipo, y debajo de ellas los resultados de evaluación de la edición seleccionada.

Una edición tiene un código, un tipo, una fecha de inicio y una fecha de fin, y puede tener un número de participantes. Ese número es solo un recuento; nunca escriba nombres.

Un resultado es el valor de una métrica de evaluación en una edición, y el valor debe estar dentro de la escala de la métrica. Se pueden añadir, editar y eliminar ediciones y resultados. Las métricas de evaluación se mantienen en Ajustes.

## Presupuesto
<!-- topic: budget -->

La página Presupuesto muestra, para un ejercicio fiscal, un resumen por fuente de financiación y moneda: el importe asignado, el importe ejecutado hasta la fecha de referencia y la tasa de ejecución. Las monedas aparecen en filas separadas y nunca se suman.

Debajo del resumen están las entradas del año y, para la entrada seleccionada, sus filas de ejecución con fecha. Se pueden añadir, editar y eliminar entradas y ejecuciones.

Las fuentes de financiación, la moneda por defecto y la opción de prorrateo se mantienen en Ajustes.

## Alertas
<!-- topic: alerts -->

La página Alertas enumera las alertas de la fecha de referencia: la gravedad (crítica, de advertencia o informativa) en texto e icono, el módulo, el asunto, la fecha de vencimiento y un mensaje. La lista se puede filtrar por módulo y por gravedad.

Haga doble clic en una alerta, pulse Intro sobre ella o use "Abrir registro" para ir a la página del registro al que se refiere.

Las alertas nunca se almacenan; se calculan cada vez a partir de los datos y de la fecha de referencia. La página solo lee datos, por lo que también funciona en el modo de solo lectura.

La barra de estado muestra los recuentos de alertas. Al iniciar, un aviso puede resumir las alertas de advertencia y críticas, con un botón que abre esta página. Cuántos días antes del vencimiento de un certificado o de un mantenimiento se genera una alerta se define en Ajustes.

## Informes
<!-- topic: reports -->

La página Informes ofrece:

- "Crear informe..." escribe el informe PDF de la fecha de referencia, interno o anonimizado. El informe anonimizado contiene solo recuentos, y los recuentos por debajo de un umbral se suprimen; el umbral se define en Ajustes. Cada página de cada informe lleva el aviso de versión preliminar, y un informe hecho a partir de la base de datos de demostración se marca como ficticio.
- "Exportar archivos CSV..." escribe los datos de los módulos en archivos CSV, un archivo por tipo de datos, en una carpeta que usted elige.
- "Exportación de validación..." escribe los archivos para la validación de los indicadores, construidos a partir de las instantáneas y de las ediciones de ejercicios. Puede registrar instantáneas retroactivas para las ediciones que no tienen una instantánea anterior e informa de cuántas.
- "Importar archivo CSV..." y "Escribir plantillas..." (véase Importación).
- La lista de instantáneas, que en esa página se llaman "registros" (véase Instantáneas).

El informe, la exportación CSV y la exportación de validación también funcionan en el modo de solo lectura.

Los archivos que usted exporta son archivos normales. Contienen datos internos y el programa no los protege: guárdelos donde solo puedan leerlos las personas autorizadas.

## Importación
<!-- topic: import -->

"Importar archivo CSV..." en la página Informes lee un archivo CSV de un tipo de datos, por ejemplo para introducir registros del pasado. "Escribir plantillas..." escribe archivos vacíos, solo con la fila de encabezado, en una carpeta que usted elige; rellénelos o edite una exportación.

El archivo debe ser UTF-8 y el separador es un punto y coma o una coma. Importe un tipo de datos cada vez e importe primero las listas a las que se refieren los demás registros: las listas (cursos, tipos de activo, métricas y fuentes de financiación), después el personal, los certificados, registros de formación y títulos, los activos, sus eventos de estado y de mantenimiento, las ediciones de ejercicios con sus países y resultados, las entradas de presupuesto y, por último, las ejecuciones presupuestarias.

Un archivo se importa por completo o no se importa. Si alguna fila tiene un problema, no se escribe nada y se informa de los problemas. La ventana de importación permite comprobar un archivo antes. La importación solo añade registros: un registro existente nunca se modifica ni se fusiona. La importación queda desactivada en el modo de solo lectura.

## Instantáneas
<!-- topic: snapshots -->

Una instantánea guarda las lecturas de los indicadores y la configuración vigente en una fecha, para que lo que se sabía en ese momento pueda verse más tarde. Se puede registrar una con "Registrar instantánea" en el Panel o con "Guardar registro" en la página Informes. Para una fecha pasada, el programa pide confirmación antes.

Las instantáneas nunca se modifican ni se eliminan. "Retirar registro..." pide un motivo y marca la instantánea como retirada: sigue almacenada y queda oculta, salvo que marque "Mostrar registros retirados".

Al iniciar, el programa puede registrar una instantánea una vez al mes por sí mismo. No lo hace en el modo de solo lectura, con datos de demostración ni cuando el reloj del equipo parece incorrecto. La sección Instantáneas de Ajustes contiene las opciones.

Registrar y retirar modifican datos, por lo que quedan desactivados en el modo de solo lectura.

## Copia de seguridad y restauración
<!-- topic: backup -->

Los datos son un único archivo SQLite en la carpeta de datos, que muestra la barra de estado. El programa hace una copia simple una vez al día y una copia antes de cada actualización de la base de datos, en la carpeta de copias de seguridad. Estas copias son tan sensibles como la base de datos y están en el mismo disco. Haga copias de seguridad cifradas a mano y guárdelas en un soporte separado.

### Hacer copia de seguridad...
<!-- topic: backup_make -->

Archivo, "Hacer copia de seguridad..." pregunta el archivo que se va a escribir y después pide una contraseña dos veces. La contraseña necesita al menos 12 caracteres y no puede ser una palabra común. El programa escribe un archivo de copia de seguridad cifrado (.cbrnbak). La contraseña nunca se almacena y no se puede recuperar: sin ella el archivo no se puede abrir.

Hacer copia de seguridad también funciona en el modo de solo lectura. Un aviso se lo recuerda cuando la última copia de seguridad cifrada es más antigua que el número de días configurado o cuando nunca se hizo una.

### Restaurar...
<!-- topic: backup_restore -->

Archivo, "Restaurar..." sustituye TODOS los datos actuales por el contenido de un archivo de copia de seguridad. Le pide que confirme y después la contraseña. Antes de copiar, el programa hace una copia de seguridad de los datos actuales y, si la restauración falla, los devuelve como estaban. Una copia de la base de datos de demostración no se puede restaurar sobre una base de datos real, ni al revés.

Restaurar queda desactivado en el modo de solo lectura. Tras una restauración correcta todas las páginas muestran los datos restaurados.

### Abrir carpeta de datos
<!-- topic: backup_folder -->

Archivo, "Abrir carpeta de datos" muestra la carpeta de datos en el Explorador de archivos de Windows. Solo abre una carpeta local existente, nunca una ubicación de red.

## Ajustes
<!-- topic: settings -->

La página Ajustes tiene una pestaña por cada grupo de ajustes y un recuadro por cada sección:

- General: el idioma, una etiqueta de operador opcional que se registra con cada cambio y los nombres de la institución y de la unidad.
- Alertas: cuántos días antes de un vencimiento o de una fecha prevista se genera una alerta.
- Metas: las metas de los indicadores, que se pueden añadir, editar, activar o desactivar y eliminar. Mientras no se defina una meta, el indicador muestra "Sin meta".
- Personal, Infraestructura, Ejercicios y Presupuesto: las listas y reglas de cada módulo, como se describe en sus páginas.
- Copia de seguridad, Informes e Instantáneas: los ajustes de las copias de seguridad, de los informes y de las instantáneas.

Algunos valores son provisionales y el comité todavía debe confirmarlos. Llevan la marca "Valor provisional - por confirmar" y un botón Confirmar.

## Privacidad
<!-- topic: privacy -->

- Los datos permanecen en este equipo, en la carpeta de datos. Por defecto es `%LOCALAPPDATA%\cbrn-readiness-dashboard`, y la barra de estado la muestra. El programa no tiene código de red: ni comprobación de actualizaciones, ni telemetría, ni envío de datos de ningún tipo.
- El personal se identifica con un código interno. El programa no guarda números de documentos de identidad, fechas de nacimiento, datos de contacto ni datos de salud.
- El registro de eventos (log) contiene solo códigos de eventos, nunca el contenido de los registros.
- El programa no puede comprobar si el disco de este equipo está cifrado. La documentación exige el cifrado completo del disco, por ejemplo con BitLocker. Los archivos que usted exporta o copia a un soporte extraíble no están protegidos por el programa.
- Un aviso advierte cuando la carpeta de datos está en un recurso compartido de red o dentro de una carpeta sincronizada con OneDrive.
- "Sensible" es solo una etiqueta de trabajo para los datos que permanecen en este equipo; no es una clasificación formal. No introduzca datos reales hasta que se respondan las cuestiones abiertas Q19, Q4, Q11 y Q13. Hasta entonces use solo datos de demostración, que llevan un aviso DEMO permanente.

## Estado preliminar
<!-- topic: preliminary -->

El aviso "Versión preliminar — indicadores no validados institucionalmente." se muestra siempre en la parte superior de la ventana. También está en todas las páginas de todo informe PDF y en el cuadro Acerca de.

Significa que los indicadores y sus umbrales no han sido validados por la institución. Los valores marcados como "Valor provisional - por confirmar" son provisionales. Trate toda cifra como preliminar.
