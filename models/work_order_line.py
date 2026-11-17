from odoo import api, fields, models, _
from odoo.exceptions import UserError


class WorkOrderLineMixin(models.AbstractModel):
    _name = 'orden.trabajo.line.mixin'
    _description = 'Propietario de línea de trabajo'

    orden_id = fields.Many2one(
        'orden.trabajo', string='Orden de trabajo', ondelete='cascade',
        required=True, index=True, check_company=True,
    )
    company_id = fields.Many2one(
        related='orden_id.company_id', store=True, index=True,
    )

    def _check_editable_order(self):
        orders = self.orden_id
        if orders:
            orders._lock_workflow()
        if any(order.state != 'draft' for order in orders):
            raise UserError(_('Cancele la orden antes de modificar sus líneas.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_editable_order()
        return records

    def write(self, vals):
        self._check_editable_order()
        if vals.get('orden_id'):
            order = self.env['orden.trabajo'].browse(vals['orden_id'])
            order.check_access('write')
            if order.state != 'draft':
                raise UserError(_('No se pueden agregar líneas a una orden confirmada.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        self._check_editable_order()
