from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    orden_trabajo_metros = fields.Float(
        string='Metros representados', digits=(16, 6), readonly=True, copy=False,
        help='Longitud total de paneles, cortes o sobrantes del movimiento. La demanda y cantidad mantienen la unidad del producto.',
    )
