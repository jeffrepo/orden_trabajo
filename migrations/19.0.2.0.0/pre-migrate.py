from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Only remove the abandoned project adaptation when no line would be orphaned.
    for table in ('orden_trabajo_corte', 'orden_trabajo_moldura_panel', 'orden_trabajo_tornilleria_accesorio'):
        cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = current_schema()", [table])
        columns = {row[0] for row in cr.fetchall()}
        if 'project_id' in columns:
            domain = 'project_id IS NOT NULL'
            if 'orden_id' in columns:
                domain += ' AND orden_id IS NULL'
            # Table names are fixed literals above, never user input.
            cr.execute('SELECT count(*) FROM "' + table + '" WHERE ' + domain)
            if cr.fetchone()[0]:
                raise RuntimeError('Existen líneas de proyectos de la adaptación anterior. Resuelva esos datos antes de actualizar; no se eliminaron registros.')
    env = api.Environment(cr, SUPERUSER_ID, {})
    for name in ('orden_trabajo_form', 'project_orden_trabajo_form'):
        view = env.ref('orden_trabajo.' + name, raise_if_not_found=False)
        if view and view.model == 'project.project':
            view.unlink()
    for suffix in ('corte', 'moldura_panel', 'tornilleria_accesorio'):
        for name in (suffix + '_project_user_rule', suffix + '_project_manager_rule'):
            rule = env.ref('orden_trabajo.' + name, raise_if_not_found=False)
            if rule:
                rule.unlink()
    for name in ('access_pro_orden_trabajo_corte', 'access_pro_orden_trabajo_moldura_panel', 'access_pro_orden_trabajo_tortilleria_accesorio', 'access_stock_lot_project_user'):
        access = env.ref('orden_trabajo.' + name, raise_if_not_found=False)
        if access:
            access.unlink()
