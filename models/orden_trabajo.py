# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import odoo.addons.decimal_precision as dp
from odoo.exceptions import UserError
import logging

class OrdenTrabajo(models.Model):
    # _inherit = 'project.project'
    _name = 'orden.trabajo'

    # name = fields.Char("Nombre", required=True, default=lambda self: self.env['ir.sequence'].next_by_code('orden.trabajo.serial'))
    # fecha = fields.Date('Fecha', required=True)
    # sale_id = fields.Many2one("sale.order", string='Orden de venta', required=True)
    # stock_picking_type_id = fields.Many2one("stock.picking.type", string='Tipo de albarán', required=True)
    # corte_ids = fields.One2many('orden.trabajo.corte', 'orden_id', string='Cortes')
    # moldura_panel_ids = fields.One2many('orden.trabajo.moldura_panel', 'orden_id', string='Molduras y paneles')
    # tornilleria_accesorio_ids = fields.One2many('orden.trabajo.tornilleria_accesorio', 'orden_id', string='Tornillería y accesorios')
    # state = fields.Selection([
    #     ('draft', 'Borrador'),
    #     ('confirm', 'Confirmado'),
    # ], string='Estado', readonly=True, copy=False, index=True, track_visibility='onchange', default='draft')


class OrdenTrabajoCortes(models.Model):
    _name = 'orden.trabajo.corte'
    _rec_name = 'lote_id'

    @api.onchange('corte1', 'corte2', 'corte3', 'corte4', 'corte5', 'corte6')
    def _total(self):
        self.total = self.corte1 + self.corte2 + self.corte3 + self.corte4 + self.corte5 + self.corte6

    @api.onchange('total')
    def _sobra(self):
        self.sobra = self.lote_id.largo - self.total

    project_id = fields.Many2one("project.project", string='Proyecto', required=True)
    lote_id = fields.Many2one("stock.production.lot", string='Lote', required=True)
    product_id = fields.Many2one(related='lote_id.product_id', string="Producto", store=True, readonly=True)
    product_qty = fields.Float(string='Cantidad', digits=dp.get_precision('Product Unit of Measure'), required=True)
    corte1 = fields.Float("Corte 1", required=True)
    corte2 = fields.Float("Corte 2", required=True)
    corte3 = fields.Float("Corte 3", required=True)
    corte4 = fields.Float("Corte 4", required=True)
    corte5 = fields.Float("Corte 5", required=True)
    corte6 = fields.Float("Corte 6", required=True)
    total = fields.Float("Total", required=True)
    sobra = fields.Float("Sobra", required=True)

class OrdenTrabajoMolduraPanel(models.Model):
    _name = 'orden.trabajo.moldura_panel'
    _rec_name = 'product_id'

    project_id = fields.Many2one("project.project", string='Proyecto', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    cantidad = fields.Float(string='Cantidad', digits=dp.get_precision('Product Unit of Measure'), required=True, default=1.0)

class OrdenTrabajoTornilleriaAccesorio(models.Model):
    _name = 'orden.trabajo.tornilleria_accesorio'
    _rec_name = 'product_id'

    project_id = fields.Many2one("project.project", string='Proyecto', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    cantidad = fields.Float(string='Cantidad', digits=dp.get_precision('Product Unit of Measure'), required=True, default=1.0)

