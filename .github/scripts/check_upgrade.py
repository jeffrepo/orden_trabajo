assert 'project_id' not in env['orden.trabajo.corte']._fields
assert 'corte_ids' not in env['project.project']._fields
assert env.ref('orden_trabajo.orden_trabajo_form').model == 'orden.trabajo'
assert not env.ref('orden_trabajo.project_orden_trabajo_form', raise_if_not_found=False)
assert env.ref('orden_trabajo.orden_trabajo_orden_trabajo_menu').parent_id == env.ref('mrp.menu_mrp_manufacturing')
print('Standalone Manufacturing orders verified; project adaptation removed')
