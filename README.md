# Órdenes de trabajo - Odoo 19

Migración del módulo original de **Odoo 10** proporcionado por el usuario.
Versión: **19.0.2.0.0**. Autor original: Rodolfo Borstcheff.

## Dónde aparece

**Fabricación > Operaciones > Órdenes de trabajo**, para administradores de
Fabricación. La vista `orden_trabajo.orden_trabajo_form` vuelve a pertenecer al
modelo independiente `orden.trabajo`. La impresión está en **Imprimir > Orden
de Trabajo**.

Dependencias: `mrp`, `sale_stock` y `project`. Para confirmar y cancelar se
necesitan también permisos de Inventario y de escritura sobre la venta vinculada.
Los permisos se comprueban con el usuario actual, sin sudo en las operaciones.

## Funcionamiento recuperado

- Nombre/secuencia, fechas, venta, tipo de albarán, estados y tres pestañas.
- Campos de producción, observaciones, revisión y autorización identificados en
  la captura/PDF y en la extensión antigua de GDOMEX.
- Confirmar consume los lotes seleccionados del almacén de la venta hacia la
  ubicación de producción del producto. Devuelve los cortes y sobrantes al
  almacén, reutilizando o creando lotes por producto, largo y compañía.
- Agrega a la venta los cortes solicitados, molduras y accesorios. Los sobrantes
  regresan al inventario; no se venden. No elimina las líneas previas de la venta.
- Los paneles son productos almacenables con seguimiento por lotes. Las cantidades
  se expresan en la unidad del producto; los cortes y el largo usan la misma unidad
  de longitud. Se conserva el precio de lista utilizado por el módulo de Odoo 10.
- Totales y sobrantes se recalculan también al importar o editar por API.
- Cada confirmación registra sus transferencias y líneas comerciales. El botón
  Transferencias permite consultar tanto operaciones originales como reversiones.

## Cancelación automática

Cancelar devuelve primero las piezas producidas a producción y después recupera
los paneles originales, mediante nuevos movimientos vinculados a los anteriores.
Elimina las líneas generadas en presupuestos. Si la venta ya está confirmada,
Odoo exige conservar las líneas: su cantidad se deja en cero y se cancelan sus
movimientos de entrega pendientes. Las demás líneas de la venta no se modifican.
Después puede corregirse y confirmarse nuevamente la orden.

Toda la operación se revierte si falla un paso. Se bloquea cuando hay facturas
vinculadas, entregas realizadas, stock insuficiente o reservado por otras
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

La adaptación anterior a Proyectos se conserva para no perder líneas que ya se
hubieran registrado: sus pestañas usan ahora `project_orden_trabajo_form`. Un
script renombra la vista anterior antes de restaurar el formulario independiente;
recalcula compañías, totales y sobrantes sin reasignar líneas de proyectos a
órdenes arbitrarias.

## Pruebas

GitHub Actions instala y actualiza con `odoo:19.0` y PostgreSQL 16. La suite incluye
las pruebas de proyectos existentes y pruebas de consumo/producción por lotes,
ventas, cancelación/reconfirmación, rollback por faltantes, bloqueo por facturas,
permisos y formulario/menú/reporte PDF. Ejecutar localmente en una base de pruebas:

```sh
odoo -d BASE_PRUEBAS -i orden_trabajo --without-demo \
  --test-enable --test-tags=/orden_trabajo --stop-after-init --no-http
```

La validación no sustituye una prueba de la base migrada con GDOMEX y los demás
addons instalados en producción.
