# Órdenes de trabajo - Odoo 19

Migración del módulo original de **Odoo 10** proporcionado por el usuario.
Versión: **19.0.2.0.2**. Autor original: Rodolfo Borstcheff.

## Dónde aparece

**Fabricación > Operaciones > Órdenes de trabajo**, para administradores de
Fabricación. La vista `orden_trabajo.orden_trabajo_form` vuelve a pertenecer al
modelo independiente `orden.trabajo`. La impresión está en **Imprimir > Orden
de Trabajo**.

Dependencias: `mrp` y `sale_stock`. No depende de Proyectos. Para confirmar y cancelar se
necesitan también permisos de Inventario y de escritura sobre la venta vinculada.
Los permisos se comprueban con el usuario actual, sin sudo en las operaciones.

## Funcionamiento recuperado

- Nombre/secuencia, fechas, venta, tipo de albarán, estados y tres pestañas.
- Campos de producción, observaciones, revisión y autorización identificados en
  la captura/PDF y en la extensión antigua de GDOMEX.
- Para productos medidos en metros, Confirmar da salida únicamente a
  `cantidad de paneles × (corte1 + corte2 + … + corte6)` desde el lote elegido
  hacia la ubicación del cliente de la venta. Cada corte registra su movimiento.
  No crea lotes ni movimientos de entrada para cortes o sobrantes.
- Ejemplo: con 11.90 M disponibles y un panel con corte de 4.50 m, salen 4.50 M
  y quedan 7.40 M en el mismo lote. La columna Sobra sigue mostrando
  `largo del panel − suma de cortes` por panel; no modifica el largo del lote.
- Los cortes se agregan a la venta como ya despachados, vinculados a esa única
  salida. Confirmar la venta antes o después de la orden no vuelve a descontarlos.
  Molduras y accesorios mantienen su flujo normal de venta y entrega.
  Las líneas previas de la venta no se modifican.
- Los paneles son productos almacenables con seguimiento por lotes. En Cortes,
  **Cantidad de paneles** es el número de piezas y **Largo del panel (m)** muestra
  el largo configurado en el lote. Los largos y cortes se ingresan en metros.
  Las unidades lineales relacionadas con el metro usan la conversión de Odoo;
  una unidad independiente denominada M, metro o metros también se interpreta
  como metros. Se conserva el precio de lista por unidad del producto.
- Los productos contados por unidades conservan el flujo anterior: consumo de
  paneles completos y producción de cortes y sobrantes en lotes por largo.
- El nuevo flujo se aplica al confirmar órdenes. No modifica transferencias ya
  realizadas; Cancelar revierte las cantidades registradas en ellas, también
  cuando pertenecen al flujo anterior.
- Totales y sobrantes se recalculan también al importar o editar por API.
- Cada confirmación registra sus transferencias y líneas comerciales. El botón
  Transferencias permite consultar tanto operaciones originales como reversiones.

## Cancelación automática

Cancelar devuelve al lote original únicamente los metros despachados, mediante
movimientos de devolución vinculados a la salida. La cantidad entregada en la
venta vuelve a cero. Para órdenes del flujo anterior, devuelve primero los
cortes y sobrantes a producción y después recupera los paneles originales.
Elimina las líneas generadas en presupuestos. Si la venta ya está confirmada,
Odoo exige conservar las líneas: su cantidad se deja en cero y se cancelan sus
movimientos de entrega pendientes. Las demás líneas de la venta no se modifican.
Después puede corregirse y confirmarse nuevamente la orden.

Toda la operación se revierte si falla un paso. Se bloquea cuando hay facturas
vinculadas, entregas externas a la orden, stock insuficiente o reservado por otras
operaciones, devoluciones manuales existentes, venta bloqueada, o lotes con
paquetes/propietario que requieren una devolución manual. Las órdenes confirmadas
antes de esta migración carecen de vínculos fiables con sus operaciones: no se
intenta adivinar qué inventario o líneas comerciales revertir.

## Reporte

Reporte QWeb reconstruido con el PDF de referencia: datos de la compañía, cliente,
proyecto, fechas, tabla de seis cortes, totales, resumen de medidas, accesorios,
molduras, observaciones y firmas. Logo/dirección proceden de la compañía de la
orden, sin datos de clientes ni marcas fijos en el código. El ZIP original no
contenía su plantilla de impresión.

El campo Proyecto usa el texto indicado en la orden; si está vacío, toma
`sale.order.proyecto` cuando GDOMEX lo proporciona y, finalmente, el nombre de la
orden. `stock.lot.largo` conserva el nombre y columna usados por GDOMEX.

## Actualización

Con el código en una carpeta llamada `orden_trabajo` dentro de addons:

```sh
odoo -d BASE_ODOO_19 -u orden_trabajo --stop-after-init
```

Para una instalación nueva, usar `-i orden_trabajo`.

La base debe haber sido migrada a Odoo 19 por separado; este addon no convierte
por sí solo una base completa de Odoo 10. Se conservan modelos/campos e IDs XML
originales para facilitar la migración de sus registros. El cambio del modelo
estándar `stock.production.lot` a `stock.lot` corresponde a la migración de la base.

Se elimina la adaptación a Proyectos que no pertenece al ZIP original. Si se
actualiza desde la primera versión 19, se retiran sus vistas y permisos. Si esa
versión contiene líneas de proyectos, la actualización se detiene sin borrarlas:
esos datos necesitan resolverse antes de instalar el módulo independiente.

## Pruebas

GitHub Actions instala y actualiza con `odoo:19.0` y PostgreSQL 16. La suite incluye
pruebas de salida de cortes sin doble descuento, lotes, conversiones de unidad,
ventas, cancelación/reconfirmación, rollback por faltantes, bloqueo por facturas,
permisos y formulario/menú/reporte PDF. Ejecutar localmente en una base de pruebas:

```sh
odoo -d BASE_PRUEBAS -i orden_trabajo --without-demo \
  --test-enable --test-tags=/orden_trabajo --stop-after-init --no-http
```

La validación no sustituye una prueba de la base migrada con GDOMEX y los demás
addons instalados en producción.
