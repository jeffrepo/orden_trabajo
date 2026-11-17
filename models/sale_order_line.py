from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    orden_trabajo_id = fields.Many2one('orden.trabajo', copy=False, index=True, ondelete='restrict')
    orden_trabajo_cycle = fields.Integer(copy=False)
