from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cuts = env['orden.trabajo.corte']
    last_id = 0
    while batch := cuts.search([('id', '>', last_id)], order='id', limit=1000):
        # These columns existed as manually/onchange-populated fields in v15.
        # Recompute them even when the database columns were already present.
        for name in ('total', 'sobra'):
            env.add_to_compute(cuts._fields[name], batch)
        batch._recompute_recordset(['total', 'sobra'])
        batch.flush_recordset(['total', 'sobra'])
        last_id = batch[-1].id
        env.invalidate_all()
