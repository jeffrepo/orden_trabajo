import importlib.util
from pathlib import Path

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestOrdenTrabajo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Orden de prueba',
            'company_id': cls.env.company.id,
            'privacy_visibility': 'employees',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Perfil de prueba',
            'is_storable': True,
            'tracking': 'lot',
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'OT-001',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
            'largo': 20.0,
        })
        cls.user = new_test_user(
            cls.env, login='ot_project_user',
            groups='base.group_user,project.group_project_user',
        )
        cls.manager = new_test_user(
            cls.env, login='ot_project_manager',
            groups='base.group_user,project.group_project_manager',
        )
        cls.models = (
            'orden.trabajo.corte',
            'orden.trabajo.moldura_panel',
            'orden.trabajo.tornilleria_accesorio',
        )

    def _values(self, model, project=None):
        values = {'project_id': (project or self.project).id}
        if model == 'orden.trabajo.corte':
            values.update(lote_id=self.lot.id, product_qty=2, corte1=1)
        else:
            values.update(product_id=self.product.id, cantidad=2)
        return values

    def test_create_batch_without_onchange(self):
        lines = self.env['orden.trabajo.corte'].create([
            dict(self._values('orden.trabajo.corte'),
                 corte1=1, corte2=2, corte3=3, corte4=4, corte5=5, corte6=1),
            dict(self._values('orden.trabajo.corte'), corte1=4),
        ])
        self.assertEqual(lines.mapped('total'), [16, 4])
        self.assertEqual(lines.mapped('sobra'), [4, 16])
        self.assertEqual(lines.mapped('product_id'), self.product)
        lines.write({'corte2': 1.5})
        self.assertEqual(lines.mapped('total'), [15.5, 5.5])
        self.assertEqual(lines.mapped('sobra'), [4.5, 14.5])
        # Quantity remains independent of the length sum, as in v15.
        lines.write({'product_qty': 3})
        self.assertEqual(lines.mapped('total'), [15.5, 5.5])

    def test_lot_changes_recompute_remaining_length(self):
        line = self.env['orden.trabajo.corte'].create(self._values('orden.trabajo.corte'))
        self.lot.largo = 30
        self.assertEqual(line.sobra, 29)
        other_product = self.env['product.product'].create({
            'name': 'Otro perfil', 'is_storable': True, 'tracking': 'lot',
        })
        other_lot = self.env['stock.lot'].create({
            'name': 'OT-002', 'product_id': other_product.id,
            'company_id': self.env.company.id, 'largo': 10,
        })
        line.lote_id = other_lot
        self.assertEqual(line.sobra, 9)
        self.assertEqual(line.product_id, other_product)
        line.corte1 = 12
        self.assertEqual(line.sobra, -2)

    def test_project_form_saves_all_line_types(self):
        with Form(self.project, view='project.edit_project') as form:
            with form.corte_ids.new() as cut:
                cut.lote_id = self.lot
                cut.product_qty = 1
                cut.corte1 = 3
                cut.corte2 = 2
                self.assertEqual(cut.total, 5)
                self.assertEqual(cut.sobra, 15)
            with form.moldura_panel_ids.new() as panel:
                panel.product_id = self.product
            with form.tornilleria_accesorio_ids.new() as accessory:
                accessory.product_id = self.product
        self.assertEqual(self.project.corte_ids.total, 5)
        self.assertEqual(self.project.corte_ids.sobra, 15)
        self.assertEqual(self.project.moldura_panel_ids.cantidad, 1)
        self.assertEqual(self.project.tornilleria_accesorio_ids.cantidad, 1)

    def test_project_user_without_pos_or_inventory(self):
        self.assertFalse(self.user.has_group('stock.group_stock_user'))
        self.assertEqual(
            self.lot.with_user(self.user).read(['largo'])[0]['largo'], 20,
        )
        with self.assertRaises(AccessError):
            self.lot.with_user(self.user).write({'largo': 21})
        for model in self.models:
            with self.subTest(model=model):
                line = self.env[model].with_user(self.user).create(self._values(model))
                field = 'product_qty' if model == 'orden.trabajo.corte' else 'cantidad'
                line.write({field: 3})
                self.assertEqual(line.read([field])[0][field], 3)
                line.unlink()

    def test_private_project_lines_follow_project_visibility(self):
        private = self.env['project.project'].create({
            'name': 'Proyecto privado', 'privacy_visibility': 'followers',
            'company_id': self.env.company.id,
        })
        lines = [self.env[model].create(self._values(model, private))
                 for model in self.models]
        for line in lines:
            with self.assertRaises(AccessError):
                line.with_user(self.user).read(['project_id'])
            self.assertEqual(line.with_user(self.manager).project_id, private)
        private.message_subscribe(partner_ids=self.user.partner_id.ids)
        for line in lines:
            self.assertEqual(line.with_user(self.user).project_id, private)

    def test_company_rules(self):
        other_company = self.env['res.company'].create({'name': 'Otra compañía OT'})
        other_project = self.env['project.project'].with_company(other_company).create({
            'name': 'Proyecto otra compañía',
            'company_id': other_company.id, 'privacy_visibility': 'employees',
        })
        other_lot = self.env['stock.lot'].with_company(other_company).create({
            'name': 'OT-OTHER', 'product_id': self.product.id,
            'company_id': other_company.id, 'largo': 10,
        })
        for model in self.models:
            values = self._values(model, other_project)
            if model == 'orden.trabajo.corte':
                values['lote_id'] = other_lot.id
            line = self.env[model].with_company(other_company).create(values)
            with self.assertRaises(AccessError):
                line.with_user(self.user).with_context(
                    allowed_company_ids=self.env.company.ids,
                ).read(['project_id'])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['orden.trabajo.corte'].with_context(
                allowed_company_ids=(self.env.company | other_company).ids,
            ).create(dict(self._values('orden.trabajo.corte'), lote_id=other_lot.id))

    def test_delete_project_removes_lines(self):
        project = self.project.copy({'name': 'Proyecto temporal'})
        lines = [self.env[model].create(self._values(model, project))
                 for model in self.models]
        project.unlink()
        for line in lines:
            self.assertFalse(line.exists())

    def test_upgrade_recomputes_existing_columns(self):
        line = self.env['orden.trabajo.corte'].create(self._values('orden.trabajo.corte'))
        self.env.flush_all()
        self.cr.execute(
            'UPDATE orden_trabajo_corte SET total = 999, sobra = 999 WHERE id = %s',
            [line.id],
        )
        self.env.invalidate_all()
        script = Path(__file__).resolve().parents[1] / 'migrations/19.0.1.0.0/post-migrate.py'
        spec = importlib.util.spec_from_file_location('ot_post_migrate', script)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.cr, '0.1')
        self.env.invalidate_all()
        self.assertEqual(line.total, 1)
        self.assertEqual(line.sobra, 19)
        self.assertEqual(line.project_id, self.project)
        self.assertEqual(line.lote_id, self.lot)

    def test_combined_views_use_odoo_19_lists(self):
        arch = etree.fromstring(self.env['project.project'].get_view(
            view_id=self.env.ref('project.edit_project').id, view_type='form',
        )['arch'])
        for field in ('corte_ids', 'moldura_panel_ids', 'tornilleria_accesorio_ids'):
            self.assertTrue(arch.xpath(f"//field[@name='{field}']/list"))
            self.assertFalse(arch.xpath(f"//field[@name='{field}']/tree"))
        lot_arch = etree.fromstring(self.env['stock.lot'].get_view(
            view_id=self.env.ref('stock.view_production_lot_form').id,
            view_type='form',
        )['arch'])
        self.assertTrue(lot_arch.xpath("//field[@name='largo']"))
