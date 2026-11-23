from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    orden_trabajo_metros = fields.Float(
        string='Metros cortados', digits=(16, 6), readonly=True, copy=False,
        help='Metros utilizados en el corte. La demanda y cantidad mantienen la unidad del producto.',
    )
