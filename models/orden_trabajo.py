from odoo import api, fields, models


class OrdenTrabajoCortes(models.Model):
    _name = 'orden.trabajo.corte'
    _inherit = 'orden.trabajo.line.mixin'
    _description = 'Corte de orden de trabajo'
    _rec_name = 'lote_id'
    _check_company_auto = True

    lote_id = fields.Many2one(
        'stock.lot', string='Lote', required=True,
        ondelete='restrict', check_company=True,
    )
    product_id = fields.Many2one(
        related='lote_id.product_id', string='Producto', store=True,
    )
    product_qty = fields.Float(
        string='Cantidad', digits='Product Unit', required=True, default=0.0,
    )
    corte1 = fields.Float(string='Corte 1', required=True, default=0.0)
    corte2 = fields.Float(string='Corte 2', required=True, default=0.0)
    corte3 = fields.Float(string='Corte 3', required=True, default=0.0)
    corte4 = fields.Float(string='Corte 4', required=True, default=0.0)
    corte5 = fields.Float(string='Corte 5', required=True, default=0.0)
    corte6 = fields.Float(string='Corte 6', required=True, default=0.0)
    total = fields.Float(string='Total', compute='_compute_total', store=True)
    sobra = fields.Float(string='Sobra', compute='_compute_sobra', store=True)

    @api.depends('corte1', 'corte2', 'corte3', 'corte4', 'corte5', 'corte6')
    def _compute_total(self):
        for line in self:
            line.total = (
                line.corte1 + line.corte2 + line.corte3
                + line.corte4 + line.corte5 + line.corte6
            )

    @api.depends('total', 'lote_id.largo')
    def _compute_sobra(self):
        for line in self:
            line.sobra = line.lote_id.largo - line.total


class OrdenTrabajoMolduraPanel(models.Model):
    _name = 'orden.trabajo.moldura_panel'
    _inherit = 'orden.trabajo.line.mixin'
    _description = 'Moldura o panel de orden de trabajo'
    _rec_name = 'product_id'
    _check_company_auto = True

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, check_company=True,
    )
    cantidad = fields.Float(
        string='Cantidad', digits='Product Unit', required=True, default=1.0,
    )


class OrdenTrabajoTornilleriaAccesorio(models.Model):
    _name = 'orden.trabajo.tornilleria_accesorio'
    _inherit = 'orden.trabajo.line.mixin'
    _description = 'Tornillería o accesorio de orden de trabajo'
    _rec_name = 'product_id'
    _check_company_auto = True

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, check_company=True,
    )
    cantidad = fields.Float(
        string='Cantidad', digits='Product Unit', required=True, default=1.0,
    )
