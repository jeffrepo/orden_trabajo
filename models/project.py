# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ast
import json
from collections import defaultdict
from datetime import timedelta, datetime
from random import randint

from odoo import api, Command, fields, models, tools, SUPERUSER_ID, _, _lt
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.tools import format_amount
from odoo.osv.expression import OR

# from .project_task_recurrence import DAYS, WEEKS
# from .project_update import STATUS_COLOR

class Project(models.Model):
    _inherit= 'project.project'

    corte_ids = fields.One2many('orden.trabajo.corte', 'project_id', string='Cortes')
    moldura_panel_ids = fields.One2many('orden.trabajo.moldura_panel', 'project_id', string='Molduras y paneles')
    tornilleria_accesorio_ids = fields.One2many('orden.trabajo.tornilleria_accesorio', 'project_id', string='Tornillería y accesorios')