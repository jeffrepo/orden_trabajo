project = env['project.project'].create({'name': 'OT-UPGRADE-PROJECT', 'company_id': env.company.id})
product = env['product.product'].create({'name': 'OT-UPGRADE-PANEL', 'is_storable': True, 'tracking': 'lot'})
lot = env['stock.lot'].create({'name': 'OT-UPGRADE-LOT', 'product_id': product.id, 'company_id': env.company.id, 'largo': 10})
line = env['orden.trabajo.corte'].create({'project_id': project.id, 'lote_id': lot.id, 'product_qty': 2, 'corte1': 3})
import importlib.util
spec = importlib.util.spec_from_file_location('migration_guard', '/migration/migrations/19.0.2.0.0/pre-migrate.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
try:
    migration.migrate(env.cr, '19.0.1.0.0')
except RuntimeError as error:
    assert 'líneas de proyectos' in str(error)
else:
    raise AssertionError('Migration must stop rather than orphan project lines')
assert line.exists() and line.project_id == project
# Remove only the synthetic fixture, then verify the empty previous installation upgrades.
line.unlink()
project.unlink()
env.cr.commit()
