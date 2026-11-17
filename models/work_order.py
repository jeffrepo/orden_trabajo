from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round


class OrdenTrabajo(models.Model):
    _name = 'orden.trabajo'
    _description = 'Orden de trabajo'
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(string='Nombre', required=True, copy=False, default='/')
    fecha = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    fecha_produccion = fields.Date(string='Fecha de producción')
    sale_id = fields.Many2one('sale.order', string='Orden de venta', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='sale_id.company_id', store=True, index=True)
    stock_picking_type_id = fields.Many2one(
        'stock.picking.type', string='Tipo de albarán', required=True, check_company=True,
    )
    project_name = fields.Char(string='Proyecto')
    observaciones = fields.Text(string='Observaciones')
    revisado_por = fields.Many2one('res.users', string='Revisado por')
    autorizado_por = fields.Many2one('res.users', string='Autorizado por')
    corte_ids = fields.One2many('orden.trabajo.corte', 'orden_id', string='Cortes', copy=True)
    moldura_panel_ids = fields.One2many('orden.trabajo.moldura_panel', 'orden_id', string='Molduras y paneles', copy=True)
    tornilleria_accesorio_ids = fields.One2many('orden.trabajo.tornilleria_accesorio', 'orden_id', string='Tornillería y accesorios', copy=True)
    state = fields.Selection([
        ('draft', 'Borrador'), ('confirm', 'Confirmado'),
    ], string='Estado', default='draft', required=True, readonly=True, copy=False, index=True)
    confirmation_number = fields.Integer(readonly=True, copy=False)
    picking_ids = fields.One2many('stock.picking', 'orden_trabajo_id', string='Transferencias', readonly=True)
    sale_line_ids = fields.One2many('sale.order.line', 'orden_trabajo_id', string='Líneas de venta generadas', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or vals.get('confirmation_number'):
                raise UserError(_('Use el botón Confirmar para procesar la orden.'))
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('orden.trabajo.serial') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'confirmation_number'} & vals.keys():
            raise UserError(_('Use los botones Confirmar o Cancelar para cambiar el estado.'))
        protected = {'sale_id', 'stock_picking_type_id', 'corte_ids', 'moldura_panel_ids', 'tornilleria_accesorio_ids'}
        if protected & vals.keys() and any(order.state == 'confirm' for order in self):
            raise UserError(_('Cancele la orden antes de modificar sus productos o su venta.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_unused(self):
        if any(order.state == 'confirm' or order.picking_ids or order.sale_line_ids for order in self):
            raise UserError(_('No se puede eliminar una orden con operaciones vinculadas.'))

    def _lock_workflow(self):
        self.check_access('write')
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM orden_trabajo WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset(['state', 'confirmation_number'])

    def _validate_confirmation(self):
        self.ensure_one()
        self._check_company()
        self.sale_id.check_access('write')
        if self.sale_id.state not in ('draft', 'sent', 'sale') or self.sale_id.locked:
            raise UserError(_('La venta debe estar activa y desbloqueada.'))
        if not (self.corte_ids or self.moldura_panel_ids or self.tornilleria_accesorio_ids):
            raise UserError(_('Agregue al menos una línea a la orden.'))
        for line in self.corte_ids:
            product = line.product_id
            if not product.is_storable or product.tracking != 'lot':
                raise UserError(_('Los paneles deben ser productos almacenables con seguimiento por lotes.'))
            if line.product_qty <= 0 or any(line[f'corte{i}'] < 0 for i in range(1, 7)):
                raise UserError(_('La cantidad debe ser positiva y los cortes no pueden ser negativos.'))
            if line.total <= 0 or float_compare(line.total, line.lote_id.largo, precision_digits=6) > 0:
                raise UserError(_('La suma de los cortes debe ser positiva y no superar el largo del panel.'))
            if not product.with_company(self.company_id).property_stock_production:
                raise UserError(_('Configure la ubicación de producción del producto.'))
        for line in self.moldura_panel_ids:
            if line.cantidad <= 0:
                raise UserError(_('Las cantidades de molduras deben ser positivas.'))
        for line in self.tornilleria_accesorio_ids:
            if line.cantidad <= 0:
                raise UserError(_('Las cantidades de accesorios deben ser positivas.'))

    def _buscar_lote_por_largo(self, product_id, largo):
        self.ensure_one()
        return self.env['stock.lot'].search([
            ('product_id', '=', product_id), ('largo', '=', largo),
            ('company_id', '=', self.company_id.id),
        ], order='id', limit=1)

    def _get_output_lot(self, product, length):
        lot = self._buscar_lote_por_largo(product.id, length)
        if not lot:
            serial = self.env['ir.sequence'].next_by_code('orden.trabajo.lote')
            lot = self.env['stock.lot'].create({
                'name': '%s - %s' % (serial, length), 'product_id': product.id,
                'company_id': self.company_id.id, 'largo': length,
            })
        return lot

    def _make_transfer(self, source, destination, entries, role, original=False):
        """entries: (lot, quantity in product UoM, original move for a return)."""
        self.ensure_one()
        picking_type = (original.picking_type_id.return_picking_type_id or original.picking_type_id) if original else self.stock_picking_type_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id, 'company_id': self.company_id.id,
            'location_id': source.id, 'location_dest_id': destination.id,
            'origin': self.name, 'orden_trabajo_id': self.id,
            'orden_trabajo_cycle': self.confirmation_number, 'orden_trabajo_role': role,
        })
        moves = self.env['stock.move'].create([{
            'product_id': lot.product_id.id, 'product_uom': lot.product_id.uom_id.id,
            'product_uom_qty': quantity, 'location_id': source.id,
            'location_dest_id': destination.id, 'picking_id': picking.id,
            'company_id': self.company_id.id,
            'origin_returned_move_id': origin.id if origin else False,
            'procure_method': 'make_to_stock',
        } for lot, quantity, origin in entries])
        moves._action_confirm(merge=False)
        # Confirmation may automatically reserve other lots. Reserve the selected lot explicitly.
        moves._do_unreserve()
        for move, (lot, quantity, origin) in zip(moves, entries):
            if source.usage == 'internal':
                reserved = move._update_reserved_quantity(quantity, source, lot_id=lot, strict=False)
                if move.product_uom.compare(reserved, quantity) < 0:
                    raise UserError(_('No hay cantidad disponible suficiente del lote %s en %s.', lot.display_name, source.display_name))
            else:
                vals = move._prepare_move_line_vals(quantity=quantity)
                vals['lot_id'] = lot.id
                self.env['stock.move.line'].create(vals)
        moves.picked = True
        picking._action_done()
        if picking.state != 'done':
            raise UserError(_('No se pudo completar la transferencia de la orden.'))
        return picking

    def _sale_line_values(self, product, quantity, length=None):
        values = {
            'order_id': self.sale_id.id, 'product_id': product.id,
            'product_uom_id': product.uom_id.id, 'product_uom_qty': quantity,
            'price_unit': product.list_price, 'orden_trabajo_id': self.id,
            'orden_trabajo_cycle': self.confirmation_number,
        }
        if length is not None:
            values['name'] = '%s - %s' % (product.display_name, length)
        return values

    def confirmar(self):
        # A savepoint also protects callers which catch UserError inside the same transaction.
        with self.env.cr.savepoint():
            self._lock_workflow()
            for order in self:
                if order.state != 'draft':
                    raise UserError(_('La orden ya está confirmada.'))
                order = order.with_company(order.company_id)
                order._validate_confirmation()
                super(OrdenTrabajo, order).write({'confirmation_number': order.confirmation_number + 1})
                outputs, sale_cuts = defaultdict(float), defaultdict(float)
                consumption = defaultdict(list)
                warehouse_stock = order.sale_id.warehouse_id.lot_stock_id
                for line in order.corte_ids:
                    production = line.product_id.with_company(order.company_id).property_stock_production
                    consumption[production].append((line.lote_id, line.product_qty, False))
                    for i in range(1, 7):
                        length = float_round(line[f'corte{i}'], precision_digits=6)
                        if length:
                            outputs[line.product_id, length] += line.product_qty
                            sale_cuts[line.product_id, length] += line.product_qty
                    remainder = float_round(line.sobra, precision_digits=6)
                    if remainder > 0:
                        outputs[line.product_id, remainder] += line.product_qty
                for production, entries in consumption.items():
                    order._make_transfer(warehouse_stock, production, entries, 'consumption')
                production_entries = defaultdict(list)
                for (product, length), quantity in outputs.items():
                    lot = order._get_output_lot(product, length)
                    production = product.with_company(order.company_id).property_stock_production
                    production_entries[production].append((lot, quantity, False))
                for production, entries in production_entries.items():
                    order._make_transfer(production, warehouse_stock, entries, 'production')
                sale_values = [order._sale_line_values(product, qty, length)
                               for (product, length), qty in sale_cuts.items()]
                for line in order.moldura_panel_ids:
                    sale_values.append(order._sale_line_values(line.product_id, line.cantidad))
                for line in order.tornilleria_accesorio_ids:
                    sale_values.append(order._sale_line_values(line.product_id, line.cantidad))
                if sale_values:
                    self.env['sale.order.line'].create(sale_values)
                super(OrdenTrabajo, order).write({'state': 'confirm'})
        return True

    def cancelar(self):
        with self.env.cr.savepoint():
            self._lock_workflow()
            for order in self:
                if order.state != 'confirm':
                    raise UserError(_('Solo se pueden cancelar órdenes confirmadas.'))
                order = order.with_company(order.company_id)
                # Historical v10 confirmations did not record their generated transfers/lines.
                if not order.confirmation_number:
                    raise UserError(_('Esta orden antigua no tiene trazabilidad de sus movimientos. Debe revisarse antes de revertirla.'))
                sale_lines = order.sale_line_ids.filtered(lambda line: line.orden_trabajo_cycle == order.confirmation_number)
                pickings = order.picking_ids.filtered(lambda p: p.orden_trabajo_cycle == order.confirmation_number and p.orden_trabajo_role != 'return')
                if order.sale_id.locked:
                    raise UserError(_('Desbloquee la venta antes de cancelar la orden.'))
                if sale_lines.invoice_lines.filtered(lambda line: line.move_id.state != 'cancel'):
                    raise UserError(_('La orden tiene líneas vinculadas a facturas. Revierta esas facturas antes de cancelar.'))
                if sale_lines.move_ids.filtered(lambda move: move.state == 'done') or any(line.qty_delivered for line in sale_lines):
                    raise UserError(_('Hay productos entregados o movimientos de venta realizados. Revíselos antes de cancelar.'))
                if pickings.move_ids.returned_move_ids.filtered(lambda move: move.state != 'cancel'):
                    raise UserError(_('Ya existen devoluciones de esta orden. Revise los movimientos para evitar una doble reversión.'))
                if pickings.filtered(lambda p: p.state != 'done'):
                    raise UserError(_('Los movimientos de la orden fueron modificados. Revise su estado antes de cancelar.'))
                # Release only the reservations generated by this work order's sales lines.
                sale_lines.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))._action_cancel()
                # Put produced pieces back into production before recovering the original panels.
                for role in ('production', 'consumption'):
                    for picking in pickings.filtered(lambda p: p.orden_trabajo_role == role):
                        entries_by_location = defaultdict(list)
                        for ml in picking.move_line_ids:
                            if ml.owner_id or ml.package_id or ml.result_package_id:
                                raise UserError(_('La reversión de lotes con propietario o paquetes requiere una devolución manual.'))
                            qty = ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
                            entries_by_location[ml.location_dest_id, ml.location_id].append((ml.lot_id, qty, ml.move_id))
                        for (source, destination), entries in entries_by_location.items():
                            order._make_transfer(source, destination, entries, 'return', original=picking)
                # Odoo forbids deleting lines on confirmed sales: retain them with zero quantity.
                confirmed_lines = sale_lines.filtered(lambda line: line.state == 'sale')
                confirmed_lines.write({'product_uom_qty': 0})
                (sale_lines - confirmed_lines).unlink()
                super(OrdenTrabajo, order).write({'state': 'draft'})
        return True

    def obtener_cortes(self, cortes):
        totals = defaultdict(float)
        for line in cortes:
            for length in [line[f'corte{i}'] for i in range(1, 7)] + [line.sobra]:
                if length > 0:
                    totals[float_round(length, precision_digits=6)] += line.product_qty
        return [{'medida': length, 'cantidad': quantity} for length, quantity in sorted(totals.items())]

    def _report_project_name(self):
        self.ensure_one()
        return self.project_name or (self.sale_id.proyecto if 'proyecto' in self.sale_id._fields else False) or self.name

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'name': _('Transferencias de la orden'), 'type': 'ir.actions.act_window',
            'res_model': 'stock.picking', 'view_mode': 'list,form',
            'domain': [('orden_trabajo_id', '=', self.id)],
        }
