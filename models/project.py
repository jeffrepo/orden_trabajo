from odoo import fields, models


class Project(models.Model):
    _inherit = 'project.project'

    corte_ids = fields.One2many(
        'orden.trabajo.corte', 'project_id', string='Cortes',
    )
    moldura_panel_ids = fields.One2many(
        'orden.trabajo.moldura_panel', 'project_id', string='Molduras y paneles',
    )
    tornilleria_accesorio_ids = fields.One2many(
        'orden.trabajo.tornilleria_accesorio', 'project_id',
        string='Tornillería y accesorios',
    )
