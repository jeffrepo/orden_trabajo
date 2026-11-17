from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    orden_trabajo_id = fields.Many2one('orden.trabajo', copy=False, index=True, ondelete='restrict')
    orden_trabajo_cycle = fields.Integer(copy=False)
    orden_trabajo_role = fields.Selection([
        ('consumption', 'Consumo'), ('production', 'Cortes y sobrantes'),
        ('return', 'Reversión'),
    ], copy=False)
