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
            if line.lote_id.largo <= 0:
                raise UserError(_('Configure un largo positivo en el lote %s.', line.lote_id.display_name))
            if line.total <= 0 or float_compare(line.total, line.lote_id.largo, precision_digits=6) > 0:
                raise UserError(_('La suma de los cortes debe ser positiva y no superar el largo del panel.'))
            if not self._uses_length_uom(product):
                if not self._uses_piece_uom(product):
                    raise UserError(_('El producto %s debe medirse en metros o unidades de panel.', product.display_name))
                if self.env['decimal.precision'].precision_get('Product Unit') < 6:
                    raise UserError(_('Para rebajar fracciones de panel, configure al menos 6 decimales en la precisión «Product Unit».'))
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

    def _make_transfer(self, source, destination, entries, role, original=False, sale_lines=None, metres=None):
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
            'sale_line_id': sale_lines[index].id if sale_lines else (origin.sale_line_id.id if origin else False),
            'to_refund': bool(origin and origin.sale_line_id),
            'orden_trabajo_metros': metres[index] if metres is not None else (
                origin.orden_trabajo_metros * quantity / origin.product_uom._compute_quantity(
                    origin.quantity, lot.product_id.uom_id, round=False,
                ) if origin and origin.quantity else 0.0
            ),
            'procure_method': 'make_to_stock',
        } for index, (lot, quantity, origin) in enumerate(entries)])
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

    def _has_uom_reference(self, unit, reference):
        if unit.parent_path and reference.parent_path:
            return unit._has_common_reference(reference)

        # Migrated units may lack the cached parent_path. Read the actual
        # references without modifying the shared UoM configuration.
        def ancestors(uom):
            ids = set()
            while uom and uom.id not in ids:
                ids.add(uom.id)
                uom = uom.relative_uom_id
            return ids

        return bool(ancestors(unit) & ancestors(reference))

    def _has_metre_reference(self, unit):
        return self._has_uom_reference(unit, self.env.ref('uom.product_uom_meter'))

    def _uses_piece_uom(self, product):
        unit = product.uom_id
        return self._has_uom_reference(unit, self.env.ref('uom.product_uom_unit')) or (
            unit.with_context(lang=None).name.strip().casefold()
            in ('uni', 'un', 'unidad', 'unidades', 'unit', 'units')
        )

    def _uses_length_uom(self, product):
        unit = product.uom_id
        return self._has_metre_reference(unit) or (
            unit.with_context(lang=None).name.strip().casefold() in ('m', 'metro', 'metros')
        )

    def _cut_product_quantity(self, product, pieces, length, source_length):
        """Convert a panel count and its length in metres to the product UoM."""
        unit = product.uom_id
        metre = self.env.ref('uom.product_uom_meter')
        if self._has_metre_reference(unit):
            return metre._compute_quantity(pieces * length, unit, round=False)
        # Older databases may have their own standalone metre unit named M.
        if unit.with_context(lang=None).name.strip().casefold() in ('m', 'metro', 'metros'):
            return pieces * length
        fraction = pieces * length / source_length
        piece_unit = self.env.ref('uom.product_uom_unit')
        if self._has_uom_reference(unit, piece_unit):
            return piece_unit._compute_quantity(fraction, unit, round=False)
        return fraction

    def _cut_quantities(self, line):
        """Round cumulative consumption so a fully used panel totals exactly one."""
        total_length = previous_quantity = 0.0
        for i in range(1, 7):
            length = float_round(line[f'corte{i}'], precision_digits=6)
            if not length:
                continue
            total_length += length
            cumulative_quantity = float_round(self._cut_product_quantity(
                line.product_id, line.product_qty, total_length, line.lote_id.largo,
            ), precision_rounding=line.product_id.uom_id.rounding)
            quantity = float_round(cumulative_quantity - previous_quantity,
                                   precision_rounding=line.product_id.uom_id.rounding)
            if quantity <= 0:
                raise UserError(_('El corte del lote %s es demasiado pequeño para la precisión de inventario.', line.lote_id.display_name))
            yield length, quantity, line.product_qty * length
            previous_quantity = cumulative_quantity

    def _sale_line_values(self, product, quantity, length=None):
        values = {
            'order_id': self.sale_id.id, 'product_id': product.id,
            'product_uom_id': product.uom_id.id, 'product_uom_qty': quantity,
            'price_unit': product.list_price, 'orden_trabajo_id': self.id,
            'orden_trabajo_cycle': self.confirmation_number,
        }
        if length is not None:
            values['name'] = '%s - %s m' % (product.display_name, length)
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
                sale_cuts = defaultdict(float)
                consumption, sale_keys, metres = [], [], []
                warehouse_stock = order.sale_id.warehouse_id.lot_stock_id
                for line in order.corte_ids:
                    for length, quantity, cut_metres in order._cut_quantities(line):
                        key = (line.product_id, length)
                        consumption.append((line.lote_id, quantity, False))
                        sale_keys.append(key)
                        metres.append(cut_metres)
                        sale_cuts[key] += quantity
                sale_values = [order._sale_line_values(product, qty, length)
                               for (product, length), qty in sale_cuts.items()]
                for line in order.moldura_panel_ids:
                    sale_values.append(order._sale_line_values(line.product_id, line.cantidad))
                for line in order.tornilleria_accesorio_ids:
                    sale_values.append(order._sale_line_values(line.product_id, line.cantidad))
                # Link direct cut deliveries before sales can procure the same quantity again.
                sale_lines = self.env['sale.order.line'].with_context(skip_procurement=True).create(sale_values)
                cut_lines = dict(zip(sale_cuts, sale_lines))
                if consumption:
                    order._make_transfer(
                        warehouse_stock, order.sale_id.partner_shipping_id.property_stock_customer,
                        consumption, 'consumption', sale_lines=[cut_lines[key] for key in sale_keys], metres=metres,
                    )
                sale_lines.with_context(skip_procurement=False)._action_launch_stock_rule()
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
                external_moves = sale_lines.move_ids - pickings.move_ids
                unlinked_lines = sale_lines.filtered(lambda line: not (line.move_ids & pickings.move_ids))
                if external_moves.filtered(lambda move: move.state == 'done') or any(line.qty_delivered for line in unlinked_lines):
                    raise UserError(_('Hay productos entregados o movimientos de venta realizados. Revíselos antes de cancelar.'))
                if pickings.move_ids.returned_move_ids.filtered(lambda move: move.state != 'cancel'):
                    raise UserError(_('Ya existen devoluciones de esta orden. Revise los movimientos para evitar una doble reversión.'))
                if pickings.filtered(lambda p: p.state != 'done'):
                    raise UserError(_('Los movimientos de la orden fueron modificados. Revise su estado antes de cancelar.'))
                # Release only the reservations generated by this work order's sales lines.
                sale_lines.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))._action_cancel()
                # Also support reversing transformations recorded by previous versions.
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
