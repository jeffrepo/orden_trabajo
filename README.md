# Órdenes de trabajo — Odoo 19

Extiende los proyectos con las pestañas **Cortes**, **Molduras y paneles** y
**Tornillería y accesorios**. Nombre técnico: `orden_trabajo`.
Versión del módulo: `19.0.1.0.0`.

## Instalación y actualización

Colocar este repositorio en una carpeta llamada `orden_trabajo` dentro de una
ruta de addons. Dependencias: `project`, `stock` y `sale`; no requiere Punto de
Venta ni GDOMEX.

En una base de Odoo 19 nueva:

```sh
odoo -d BASE_DE_PRUEBAS -i orden_trabajo --stop-after-init
```

En una base **ya migrada a Odoo 19**, actualizar el módulo:

```sh
odoo -d BASE_DE_PRUEBAS -u orden_trabajo --stop-after-init
```

Este repositorio migra el código del addon; no convierte por sí solo una base de
Odoo 15 a Odoo 19. La migración de la base y de los addons estándar debe haber
resuelto el cambio de `stock.production.lot` a `stock.lot`. Probar primero en
una copia de la base con los demás módulos utilizados en producción.

## Uso y permisos

Abrir el formulario de un proyecto y completar sus pestañas de trabajo.
En Cortes, seleccionar un lote existente y registrar la cantidad y hasta seis
longitudes de corte. Los seis cortes y el largo del lote deben usar la misma
unidad de longitud:

- `total = corte1 + corte2 + corte3 + corte4 + corte5 + corte6`.
- `sobra = lote.largo - total`.
- La cantidad de piezas no multiplica las longitudes; se conserva el cálculo
  original. Un sobrante negativo indica que los cortes exceden el largo.
- Los resultados se almacenan y recalculan en formularios, importaciones y API,
  también al cambiar el lote o su largo.

Los usuarios de Proyectos pueden gestionar las líneas de los proyectos que
pueden ver y consultar lotes de sus compañías habilitadas. Para crear lotes o
editar su largo necesitan permisos de Inventario. Los administradores de
Proyectos pueden acceder también a proyectos privados dentro de sus compañías.
Las líneas se eliminan junto con su proyecto.

## Cambios respecto a Odoo 15

- Dependencias explícitas de Proyectos e Inventario.
- `stock.production.lot` → `stock.lot`.
- Vistas `tree` → `list`, compatibles con Odoo 19.
- Precisión decimal `Product Unit`, utilizada por Inventario en Odoo 19.
- Eliminación de imports obsoletos (`decimal_precision`, `_lt`,
  `odoo.osv.expression`) y código sin uso.
- Permisos de Proyectos en lugar de Punto de Venta, con reglas por compañía
  y visibilidad del proyecto.
- Campos calculados almacenados en lugar de resultados dependientes solamente
  de `onchange`.
- Script de actualización que recalcula los totales y sobrantes de las líneas
  existentes; conserva los nombres de modelos, campos e identificadores XML.

### Qué ocurrió con el bloque comentado

El commit `3cb0ae4` de abril de 2022 deshabilitó la clase `orden.trabajo`.
Las líneas activas ya utilizan `project_id`, y la vista hereda
`project.edit_project`. La clase comentada utilizaba `orden_id`, un inverso
que no existe en estas líneas, y una secuencia no incluida en el repositorio.

Por eso se conserva la integración sobre `project.project` y se elimina ese
bloque inactivo. No se crean órdenes independientes ni se añaden los campos
comentados de fecha, venta, tipo de operación o estado. Si una base antigua
todavía contiene registros de aquel modelo independiente, requiere analizar y
migrar esos registros antes de actualizar.

### Integración con GDOMEX

GDOMEX define `stock.lot.largo`. Este addon declara el mismo campo Float y
columna, de modo que puede funcionar solo y utilizar los valores existentes
cuando GDOMEX está instalado. La vista del lote se aplica con prioridad 10,
antes de la vista actual de GDOMEX (prioridad 16), que reemplaza el grupo
principal y ya muestra Largo.

El reporte y el asistente de órdenes de trabajo de GDOMEX siguen perteneciendo
a ese otro addon. No se modifican en esta migración.

## Pruebas

```sh
odoo -d BASE_DE_PRUEBAS -i orden_trabajo --without-demo \
  --test-enable --test-tags=/orden_trabajo --stop-after-init --no-http
```

GitHub Actions ejecuta instalación y actualización con la imagen oficial
`odoo:19.0` y PostgreSQL 16. La suite cubre creación por lotes sin onchange,
recálculo al cambiar cortes/lotes, formularios, permisos sin Punto de Venta,
proyectos privados, compañías, borrado de proyectos, recálculo de datos
existentes y vistas combinadas. No prueba la migración completa de una base
15 ni la combinación con addons Enterprise o GDOMEX.

Referencias: [ORM de Odoo 19](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html),
[vistas de Odoo 19](https://www.odoo.com/documentation/19.0/developer/reference/user_interface/view_architectures.html),
[código de Inventario](https://github.com/odoo/odoo/blob/19.0/addons/stock/models/stock_move.py).
