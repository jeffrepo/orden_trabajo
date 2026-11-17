from odoo import fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    # Same field/column used by GDOMEX; preserve existing lengths.
    largo = fields.Float(string='Largo')
