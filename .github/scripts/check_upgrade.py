project = env['project.project'].search([('name', '=', 'OT-UPGRADE-PROJECT')])
assert len(project) == 1
line = project.corte_ids
assert len(line) == 1
assert line.product_qty == 2 and line.total == 3 and line.sobra == 7
assert not line.orden_id and line.company_id == project.company_id
assert env.ref('orden_trabajo.orden_trabajo_form').model == 'orden.trabajo'
assert env.ref('orden_trabajo.project_orden_trabajo_form').model == 'project.project'
assert env.ref('orden_trabajo.orden_trabajo_orden_trabajo_menu').parent_id == env.ref('mrp.menu_mrp_manufacturing')
print('Previous project data, views and new Manufacturing menu verified')
