import base64
import logging
from unittest.mock import patch

from lxml import etree, html as html_parser

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..models.work_order import OrdenTrabajo


@tagged('post_install', '-at_install')
class TestWorkOrder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['decimal.precision'].search([('name', '=', 'Product Unit')]).digits = 6
        cls.env['uom.uom'].invalidate_model(['rounding'])
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

    def test_delivered_products_block_cancellation(self):
        self.sale.action_confirm()
        self.order.confirmar()
        line = self.order.sale_line_ids.filtered(lambda line: line.product_id == self.panel)
        moves = line.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
        moves._action_assign()
        self.assertTrue(moves)
        self.assertEqual(sum(moves.mapped('quantity')), 5)
        moves.picked = True
        moves._action_done()
        with self.assertRaises(UserError):
            self.order.cancelar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(len(self.order.picking_ids), 2)
        self.assertEqual(line.product_uom_qty, 5)

    def test_same_product_with_two_source_lots_keeps_lot_identity(self):
        lot = self.env['stock.lot'].create({
            'name': 'PANEL-10', 'product_id': self.panel.id,
            'company_id': self.env.company.id, 'largo': 10,
        })
        self.env['stock.quant']._update_available_quantity(self.panel, self.stock, 2, lot_id=lot)
        self.order.write({'corte_ids': [Command.create({'lote_id': lot.id, 'product_qty': 2, 'corte1': 4})]})
        self.order.confirmar()
        consumed = self.order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'consumption').move_line_ids
        self.assertEqual(sum(consumed.filtered(lambda ml: ml.lot_id == self.lot).mapped('quantity')), 5)
        self.assertEqual(sum(consumed.filtered(lambda ml: ml.lot_id == lot).mapped('quantity')), 2)
        self.order.cancelar()
        self.assertEqual(self._available(self.lot), 5)
        self.assertEqual(self._available(lot), 2)

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

    def test_manufacturing_permissions(self):
        manager = new_test_user(self.env, login='ot_mrp', groups='mrp.group_mrp_manager,sales_team.group_sale_manager')
        order = self.order.with_user(manager)
        order.confirmar()
        order.cancelar()
        other_user = new_test_user(self.env, login='ot_other_user', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.order.with_user(other_user).read(['name'])
        with self.assertRaises(AccessError):
            self.order.corte_ids.with_user(other_user).read(['product_qty'])

    def test_menu_form_and_report(self):
        menu = self.env.ref('orden_trabajo.orden_trabajo_orden_trabajo_menu')
        self.assertEqual(menu.parent_id, self.env.ref('mrp.menu_mrp_manufacturing'))
        self.assertEqual(self.env.ref('orden_trabajo.orden_trabajo_form').model, 'orden.trabajo')
        self.assertFalse(self.env.ref('orden_trabajo.project_orden_trabajo_form', raise_if_not_found=False))
        self.assertNotIn('project_id', self.env['orden.trabajo.corte']._fields)
        with Form(self.order, view='orden_trabajo.orden_trabajo_form') as form:
            form.observaciones = 'Observación de prueba'
        report = self.env['ir.actions.report']
        html, _ = report._render_qweb_html('orden_trabajo.action_report_orden_trabajo', self.order.ids)
        for text in ('ORDEN DE PRODUCCIÓN', 'TORNILLERÍA Y ACCESORIOS', 'MOLDURAS', '32.50', '35.00', 'Observación de prueba'):
            self.assertIn(text, html.decode())
        # Odoo rebuilds minimal_layout after rendering the report. Strip its
        # external assets at that final boundary because this suite uses --no-http.
        prepare_html = type(report)._prepare_html

        def offline_html(value):
            if not value:
                return value
            document = html_parser.fromstring(value)
            for asset in document.xpath('//link | //script'):
                asset.getparent().remove(asset)
            return etree.tostring(document, method='html', encoding='unicode')

        def prepare_offline(report_self, *args, **kwargs):
            bodies, ids, header, footer, paper = prepare_html(report_self, *args, **kwargs)
            return [offline_html(body) for body in bodies], ids, offline_html(header), offline_html(footer), paper

        with patch.object(type(report), '_prepare_html', prepare_offline):
            pdf, kind = report.with_context(force_report_rendering=True)._render_qweb_pdf(
                'orden_trabajo.action_report_orden_trabajo', self.order.ids,
            )
        self.assertEqual(kind, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))
        logging.getLogger(__name__).info('OT_REPORT_PDF_BASE64=%s', base64.b64encode(pdf).decode())

    def test_company_isolation(self):
        company = self.env['res.company'].create({'name': 'Otra compañía OT'})
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        sale = self.env['sale.order'].with_company(company).create({
            'partner_id': self.partner.id, 'warehouse_id': warehouse.id,
        })
        order = self.env['orden.trabajo'].with_company(company).create({
            'sale_id': sale.id, 'stock_picking_type_id': warehouse.int_type_id.id,
        })
        user = new_test_user(self.env, login='ot_company_user', groups='mrp.group_mrp_manager,sales_team.group_sale_manager')
        with self.assertRaises(AccessError):
            order.with_user(user).with_context(allowed_company_ids=self.env.company.ids).read(['name'])
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['orden.trabajo.corte'].with_context(
                allowed_company_ids=(self.env.company | company).ids,
            ).create({'orden_id': order.id, 'lote_id': self.lot.id, 'product_qty': 1, 'corte1': 1})

    def _create_length_order(self, unit, pieces=1, cut1=4.5, cut2=0):
        product = self.env['product.product'].create({
            'name': 'Panel en metros', 'is_storable': True, 'tracking': 'lot',
            'uom_id': unit.id, 'list_price': 25,
        })
        lot = self.env['stock.lot'].create({
            'name': 'PANEL-11.90', 'product_id': product.id,
            'company_id': self.env.company.id, 'largo': 11.9,
        })
        order = self.env['orden.trabajo'].create({
            'sale_id': self.sale.id, 'stock_picking_type_id': self.warehouse.int_type_id.id,
            'corte_ids': [Command.create({
                'lote_id': lot.id, 'product_qty': pieces, 'corte1': cut1, 'corte2': cut2,
            })],
        })
        return order, product, lot

    def test_metre_cut_remainder_and_cancellation(self):
        metre = self.env.ref('uom.product_uom_meter')
        metre.name = 'M'
        order, product, lot = self._create_length_order(metre)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 11.9, lot_id=lot)
        self.assertAlmostEqual(order.corte_ids.largo_lote, 11.9)
        self.assertAlmostEqual(order.corte_ids.total, 4.5)
        self.assertAlmostEqual(order.corte_ids.sobra, 7.4)
        order.confirmar()
        cut = order._buscar_lote_por_largo(product.id, 4.5)
        remainder = order._buscar_lote_por_largo(product.id, 7.4)
        self.assertAlmostEqual(self._available(lot), 0)
        self.assertAlmostEqual(self._available(cut), 4.5)
        self.assertAlmostEqual(self._available(remainder), 7.4)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 4.5)
        self.assertEqual(order.sale_line_ids.product_uom_id, metre)
        self.assertEqual(order.sale_line_ids.price_unit, 25)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 11.9)
        self.assertAlmostEqual(self._available(cut), 0)
        self.assertAlmostEqual(self._available(remainder), 0)
        self.assertFalse(order.sale_line_ids)
        order.confirmar()
        self.assertAlmostEqual(self._available(remainder), 7.4)

    def test_custom_m_unit_multiple_panels(self):
        custom_m = self.env['uom.uom'].create({'name': 'M'})
        order, product, lot = self._create_length_order(custom_m, pieces=3, cut1=2, cut2=2.5)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 35.7, lot_id=lot)
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 0)
        self.assertAlmostEqual(self._available(order._buscar_lote_por_largo(product.id, 2)), 6)
        self.assertAlmostEqual(self._available(order._buscar_lote_por_largo(product.id, 2.5)), 7.5)
        self.assertAlmostEqual(self._available(order._buscar_lote_por_largo(product.id, 7.4)), 22.2)
        self.assertEqual(sorted(order.sale_line_ids.mapped('product_uom_qty')), [6, 7.5])
        self.assertAlmostEqual(sum(order.picking_ids.filtered(
            lambda picking: picking.orden_trabajo_role == 'production',
        ).move_ids.mapped('quantity')), 35.7)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 35.7)

    def test_length_uom_conversion_and_confirmed_sale_reversal(self):
        cm = self.env.ref('uom.product_uom_cm')
        cm.active = True
        order, product, lot = self._create_length_order(cm)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1190, lot_id=lot)
        self.sale.action_confirm()
        order.confirmar()
        remainder = order._buscar_lote_por_largo(product.id, 7.4)
        self.assertAlmostEqual(self._available(lot), 0)
        self.assertAlmostEqual(self._available(remainder), 740)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 450)
        self.assertEqual(order.sale_line_ids.product_uom_id, cm)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 1190)
        self.assertAlmostEqual(self._available(remainder), 0)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 0)

    def _clear_uom_parent_paths(self, units):
        units.flush_recordset(['parent_path'])
        self.cr.execute('UPDATE uom_uom SET parent_path = NULL WHERE id IN %s', [tuple(units.ids)])
        units.invalidate_recordset(['parent_path'])

    def test_original_example_consumes_five_and_produces_seven_three_two(self):
        unit = self.env['uom.uom'].create({'name': 'UNI'})
        order, product, lot = self._create_length_order(unit, pieces=3)
        order.write({'corte_ids': [Command.create({
            'lote_id': lot.id, 'product_qty': 2, 'corte1': 4.5, 'corte2': 4.5,
        })]})
        self.env['stock.quant']._update_available_quantity(product, self.stock, 5, lot_id=lot)
        self._clear_uom_parent_paths(unit | self.env.ref('uom.product_uom_meter'))
        self.env['decimal.precision'].search([('name', '=', 'Product Unit')]).digits = 2
        self.env['uom.uom'].invalidate_model(['rounding'])
        order.confirmar()
        for line, remainder in zip(order.corte_ids, (7.4, 2.9)):
            self.assertAlmostEqual(line.sobra, remainder)
        self.assertAlmostEqual(self._available(lot), 0)
        consumed = order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'consumption')
        produced = order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'production')
        self.assertEqual(sorted(consumed.move_ids.mapped('quantity')), [2, 3])
        self.assertEqual(consumed.location_dest_id.usage, 'production')
        self.assertEqual(produced.location_dest_id, self.stock)
        for length, pieces in ((4.5, 7), (7.4, 3), (2.9, 2)):
            output = order._buscar_lote_por_largo(product.id, length)
            self.assertTrue(output)
            self.assertAlmostEqual(self._available(output), pieces)
        self.assertAlmostEqual(sum(consumed.move_ids.mapped('orden_trabajo_metros')), 59.5)
        self.assertAlmostEqual(sum(produced.move_ids.mapped('orden_trabajo_metros')), 59.5)
        self.assertEqual(order.sale_line_ids.product_uom_qty, 7)
        self.assertEqual(order.sale_line_ids.qty_delivered, 0)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 5)
        for length in (4.5, 7.4, 2.9):
            self.assertAlmostEqual(self._available(order._buscar_lote_por_largo(product.id, length)), 0)
        self.assertFalse(order.sale_line_ids)

    def test_reuses_matching_lots_and_preserves_their_existing_stock(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_unit'), pieces=3)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 3, lot_id=lot)
        cut = order._get_output_lot(product, 4.5)
        remainder = order._get_output_lot(product, 7.4)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 2, lot_id=cut)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 4, lot_id=remainder)
        before = self.env['stock.lot'].search([('product_id', '=', product.id)])
        order.confirmar()
        self.assertEqual(self.env['stock.lot'].search([('product_id', '=', product.id)]), before)
        self.assertEqual(self._available(cut), 5)
        self.assertEqual(self._available(remainder), 7)
        order.cancelar()
        self.assertEqual(self._available(lot), 3)
        self.assertEqual(self._available(cut), 2)
        self.assertEqual(self._available(remainder), 4)

    def test_output_lot_must_match_product_and_company(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_unit'))
        other_company = self.env['res.company'].create({'name': 'Compañía de otro sobrante'})
        wrong_product = self.env['stock.lot'].create({
            'name': 'SOBRA-OTRO-PRODUCTO', 'product_id': self.panel.id,
            'company_id': self.env.company.id, 'largo': 7.4,
        })
        wrong_company = self.env['stock.lot'].create({
            'name': 'SOBRA-OTRA-COMPANIA', 'product_id': product.id,
            'company_id': other_company.id, 'largo': 7.4,
        })
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1, lot_id=lot)
        order.confirmar()
        remainder = order._buscar_lote_por_largo(product.id, 7.4)
        self.assertTrue(remainder)
        self.assertNotIn(remainder, wrong_product | wrong_company)
        self.assertEqual(remainder.company_id, order.company_id)
        self.assertEqual(remainder.product_id, product)
        self.assertEqual(self._available(remainder), 1)

    def test_all_six_cuts_without_remainder(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_unit'), pieces=2)
        lot.largo = 6
        order.corte_ids.write({f'corte{i}': 1 for i in range(1, 7)})
        self.env['stock.quant']._update_available_quantity(product, self.stock, 2, lot_id=lot)
        order.confirmar()
        self.assertEqual(order.corte_ids.sobra, 0)
        self.assertEqual(self._available(lot), 0)
        self.assertEqual(self._available(order._buscar_lote_por_largo(product.id, 1)), 12)
        self.assertFalse(order._buscar_lote_por_largo(product.id, 0))
        self.assertEqual(order.sale_line_ids.product_uom_qty, 12)
        order.cancelar()
        self.assertEqual(self._available(lot), 2)

    def _record_previous_direct_delivery(self, order, quantity):
        """Reproduce persisted direct/fractional deliveries from 19.0.2.0.2–4."""
        line = order.corte_ids.ensure_one()
        super(OrdenTrabajo, order).write({'confirmation_number': 1})
        sale_line = self.env['sale.order.line'].with_context(skip_procurement=True).create(
            order._sale_line_values(line.product_id, quantity, line.corte1))
        order._make_transfer(self.stock, self.partner.property_stock_customer,
            [(line.lote_id, quantity, False)], 'consumption', sale_lines=[sale_line],
            metres=[line.product_qty * line.total])
        super(OrdenTrabajo, order).write({'state': 'confirm'})
        return sale_line

    def test_previous_fractional_order_can_be_cancelled_then_reconfirmed(self):
        order, product, lot = self._create_length_order(self.env['uom.uom'].create({'name': 'UNI'}))
        self.env['stock.quant']._update_available_quantity(product, self.stock, 5, lot_id=lot)
        sale_line = self._record_previous_direct_delivery(order, 0.378151)
        original = order.picking_ids.move_ids
        self.assertAlmostEqual(self._available(lot), 4.621849)
        self.sale.action_confirm()
        self.assertEqual(sale_line.move_ids, original)
        self.assertAlmostEqual(sale_line.qty_delivered, 0.378151)
        lot.largo = 12
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 5)
        returned = order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'return').move_ids
        self.assertAlmostEqual(returned.quantity, 0.378151)
        self.assertAlmostEqual(returned.orden_trabajo_metros, 4.5)
        self.assertAlmostEqual(sale_line.product_uom_qty, 0)
        self.assertAlmostEqual(sale_line.qty_delivered, 0)
        lot.largo = 11.9
        order.confirmar()
        cycle = order.picking_ids.filtered(lambda p: p.orden_trabajo_cycle == 2)
        self.assertEqual(len(cycle), 2)
        self.assertEqual(cycle.filtered(lambda p: p.orden_trabajo_role == 'consumption').move_ids.quantity, 1)
        self.assertEqual(cycle.filtered(lambda p: p.orden_trabajo_role == 'production').move_ids.mapped('quantity'), [1, 1])
        source_quants = self.env['stock.quant'].search([('lot_id', '=', lot.id), ('location_id', '=', self.stock.id)])
        self.assertAlmostEqual(sum(source_quants.mapped('quantity')), 4)
        self.assertEqual(self._available(order._buscar_lote_por_largo(product.id, 7.4)), 1)
        order.cancelar()
        self.assertEqual(self._available(lot), 5)

    def test_previous_direct_metre_delivery_can_be_cancelled(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_meter'))
        self.env['stock.quant']._update_available_quantity(product, self.stock, 11.9, lot_id=lot)
        self._record_previous_direct_delivery(order, 4.5)
        self.assertAlmostEqual(self._available(lot), 7.4)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 11.9)
        self.assertFalse(order.sale_line_ids)

    def test_missing_parent_path_preserves_metre_conversion(self):
        cm = self.env.ref('uom.product_uom_cm')
        cm.active = True
        order, product, lot = self._create_length_order(cm)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1190, lot_id=lot)
        self._clear_uom_parent_paths(cm)
        order.confirmar()
        self.assertEqual(self._available(lot), 0)
        self.assertEqual(self._available(order._buscar_lote_por_largo(product.id, 4.5)), 450)
        self.assertEqual(self._available(order._buscar_lote_por_largo(product.id, 7.4)), 740)
        order.cancelar()
        self.assertEqual(self._available(lot), 1190)

    def test_positive_lot_length_is_required_before_any_movement(self):
        self.lot.largo = 0
        with self.assertRaisesRegex(UserError, 'largo positivo'):
            self.order.confirmar()
        self.assertEqual(self.order.state, 'draft')
        self.assertFalse(self.order.picking_ids)
        self.assertFalse(self.order.sale_line_ids)

