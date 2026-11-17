from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model in ('orden.trabajo.corte', 'orden.trabajo.moldura_panel', 'orden.trabajo.tornilleria_accesorio'):
        last_id = 0
        records = env[model]
        names = ['company_id'] + (['total', 'sobra'] if model == 'orden.trabajo.corte' else [])
        while batch := records.search([('id', '>', last_id)], order='id', limit=1000):
            for name in names:
                env.add_to_compute(records._fields[name], batch)
            batch._recompute_recordset(names)
            batch.flush_recordset(names)
            last_id = batch[-1].id
            env.invalidate_all()
