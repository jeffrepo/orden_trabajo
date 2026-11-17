import base64
import logging

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestWorkOrder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente de prueba'})
        cls.panel = cls.env['product.product'].create({
            'name': 'Panel de prueba', 'is_storable': True, 'tracking': 'lot', 'list_price': 25,
        })
        cls.accessory = cls.env['product.product'].create({'name': 'Accesorio de prueba', 'list_price': 3})
        cls.lot = cls.env['stock.lot'].create({
            'name': 'PANEL-13.5', 'product_id': cls.panel.id,
            'company_id': cls.env.company.id, 'largo': 13.5,
        })
        cls.env['stock.quant']._update_available_quantity(cls.panel, cls.stock, 5, lot_id=cls.lot)
        cls.sale = cls.env['sale.order'].create({
            'partner_id': cls.partner.id, 'warehouse_id': cls.warehouse.id,
            'order_line': [Command.create({'product_id': cls.accessory.id, 'product_uom_qty': 9})],
        })
        cls.original_sale_line = cls.sale.order_line
        cls.order = cls.env['orden.trabajo'].create({
            'sale_id': cls.sale.id, 'stock_picking_type_id': cls.warehouse.int_type_id.id,
            'project_name': 'Proyecto de prueba',
            'corte_ids': [Command.create({'lote_id': cls.lot.id, 'product_qty': 5, 'corte1': 6.5})],
            'moldura_panel_ids': [Command.create({'product_id': cls.accessory.id, 'cantidad': 2})],
            'tornilleria_accesorio_ids': [Command.create({'product_id': cls.accessory.id, 'cantidad': 3})],
        })

    def _available(self, lot):
        return self.env['stock.quant']._get_available_quantity(lot.product_id, self.stock, lot_id=lot)

    def test_confirm_cancel_reconfirm(self):
        self.order.confirmar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(self.order.picking_ids.mapped('state'), ['done', 'done'])
        self.assertEqual(self._available(self.lot), 0)
        cut = self.order._buscar_lote_por_largo(self.panel.id, 6.5)
        remainder = self.order._buscar_lote_por_largo(self.panel.id, 7)
        self.assertEqual(self._available(cut), 5)
        self.assertEqual(self._available(remainder), 5)
        self.assertEqual(len(self.order.sale_line_ids), 3)
        self.assertEqual(self.original_sale_line.product_uom_qty, 9)
        with self.assertRaises(UserError):
            self.order.confirmar()
        self.assertEqual(len(self.order.picking_ids), 2)
        self.order.cancelar()
        self.assertEqual(self.order.state, 'draft')
        self.assertEqual(self._available(self.lot), 5)
        self.assertEqual(self._available(cut), 0)
        self.assertEqual(self._available(remainder), 0)
        self.assertFalse(self.order.sale_line_ids)
        self.assertEqual(self.sale.order_line, self.original_sale_line)
        self.assertEqual(len(self.order.picking_ids), 4)
        self.assertTrue(self.order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'return').move_ids.origin_returned_move_id)
        self.order.confirmar()
        self.assertEqual(self.order.confirmation_number, 2)
        self.assertEqual(len(self.order.picking_ids), 6)
        self.assertEqual(len(self.order.sale_line_ids), 3)

    def test_same_length_cut_and_remainder_are_not_both_sold(self):
        self.lot.largo = 14
        self.order.corte_ids.corte1 = 7
        self.order.confirmar()
        output = self.order._buscar_lote_por_largo(self.panel.id, 7)
        self.assertEqual(self._available(output), 10)
        sold = self.order.sale_line_ids.filtered(lambda line: line.product_id == self.panel)
        self.assertEqual(sold.product_uom_qty, 5)

    def test_selected_lots_and_multiple_products(self):
        other = self.env['product.product'].create({'name': 'Segundo panel', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({'name': 'SEGUNDO', 'product_id': other.id, 'company_id': self.env.company.id, 'largo': 10})
        self.env['stock.quant']._update_available_quantity(other, self.stock, 2, lot_id=lot)
        self.order.write({'corte_ids': [Command.create({'lote_id': lot.id, 'product_qty': 2, 'corte1': 3, 'corte2': 3})]})
        self.order.confirmar()
        self.assertEqual(self._available(lot), 0)
        self.assertEqual(self._available(self.order._buscar_lote_por_largo(other.id, 3)), 4)
        self.assertEqual(self._available(self.order._buscar_lote_por_largo(other.id, 4)), 2)
        line = self.order.sale_line_ids.filtered(lambda line: line.product_id == other)
        self.assertIn('Segundo panel', line.name)
        self.assertEqual(line.product_uom_qty, 4)
        self.order.cancelar()
        self.assertEqual(self._available(lot), 2)
        self.assertEqual(self._available(self.lot), 5)

    def test_confirmation_failure_rolls_back_all_effects(self):
        self.order.corte_ids.product_qty = 6
        with self.assertRaises(UserError):
            self.order.confirmar()
        self.assertEqual(self.order.state, 'draft')
        self.assertEqual(self.order.confirmation_number, 0)
        self.assertFalse(self.order.picking_ids)
        self.assertFalse(self.order.sale_line_ids)
        self.assertEqual(self._available(self.lot), 5)
        self.order.corte_ids.write({'product_qty': 5, 'corte1': 14})
        with self.assertRaises(UserError):
            self.order.confirmar()
        self.assertFalse(self.order.picking_ids)

    def test_cancellation_shortage_keeps_confirmation_intact(self):
        self.order.confirmar()
        lot = self.order._buscar_lote_por_largo(self.panel.id, 6.5)
        self.env['stock.quant']._update_available_quantity(self.panel, self.stock, -1, lot_id=lot)
        with self.assertRaises(UserError):
            self.order.cancelar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(len(self.order.picking_ids), 2)
        self.assertEqual(len(self.order.sale_line_ids), 3)
        self.assertEqual(self._available(self.lot), 0)

    def test_cancel_on_confirmed_sale_zeroes_only_generated_lines(self):
        self.sale.action_confirm()
        self.order.confirmar()
        lines = self.order.sale_line_ids
        self.order.cancelar()
        self.assertEqual(lines.mapped('product_uom_qty'), [0, 0, 0])
        self.assertEqual(self.original_sale_line.product_uom_qty, 9)
        self.assertFalse(lines.move_ids.filtered(lambda m: m.state not in ('cancel', 'done')))
        self.assertEqual(self._available(self.lot), 5)

    def test_invoiced_lines_block_cancellation(self):
        self.order.confirmar()
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.accessory.id, 'quantity': 1,
                'sale_line_ids': [Command.link(self.order.sale_line_ids[0].id)],
            })],
        })
        with self.assertRaises(UserError):
            self.order.cancelar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(len(self.order.picking_ids), 2)
        self.assertTrue(invoice.exists())

    def test_confirmed_order_cannot_be_edited_or_deleted(self):
        self.order.confirmar()
        for operation in (
            lambda: self.order.corte_ids.write({'corte1': 2}),
            lambda: self.order.corte_ids.unlink(),
            lambda: self.order.write({'state': 'draft'}),
            lambda: self.order.unlink(),
        ):
            with self.assertRaises(UserError):
                operation()

    def test_manufacturing_permissions_and_project_separation(self):
        manager = new_test_user(self.env, login='ot_mrp', groups='mrp.group_mrp_manager,sales_team.group_sale_manager')
        order = self.order.with_user(manager)
        order.confirmar()
        order.cancelar()
        project_user = new_test_user(self.env, login='ot_project_only', groups='project.group_project_user')
        with self.assertRaises(AccessError):
            self.order.with_user(project_user).read(['name'])
        with self.assertRaises(AccessError):
            self.order.corte_ids.with_user(project_user).read(['product_qty'])

    def test_menu_form_and_report(self):
        menu = self.env.ref('orden_trabajo.orden_trabajo_orden_trabajo_menu')
        self.assertEqual(menu.parent_id, self.env.ref('mrp.menu_mrp_manufacturing'))
        self.assertEqual(self.env.ref('orden_trabajo.orden_trabajo_form').model, 'orden.trabajo')
        self.assertEqual(self.env.ref('orden_trabajo.project_orden_trabajo_form').model, 'project.project')
        with Form(self.order, view='orden_trabajo.orden_trabajo_form') as form:
            form.observaciones = 'Observación de prueba'
        report = self.env['ir.actions.report']
        html, _ = report._render_qweb_html('orden_trabajo.action_report_orden_trabajo', self.order.ids)
        for text in ('ORDEN DE PRODUCCIÓN', 'TORNILLERÍA Y ACCESORIOS', 'MOLDURAS', '32.50', '35.00', 'Observación de prueba'):
            self.assertIn(text, html.decode())
        # Inline report CSS makes the PDF independent of external asset requests.
        pdf, kind = report.with_context(force_report_rendering=True)._render_qweb_pdf(
            'orden_trabajo.action_report_orden_trabajo', self.order.ids,
        )
        self.assertEqual(kind, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))
        logging.getLogger(__name__).info('OT_REPORT_PDF_BASE64=%s', base64.b64encode(pdf).decode())
