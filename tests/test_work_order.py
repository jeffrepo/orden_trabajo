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
        self.assertEqual(self.order.picking_ids.mapped('state'), ['done'])
        self.assertAlmostEqual(self._available(self.lot), 2.592593)
        self.assertAlmostEqual(self.order.picking_ids.move_ids.quantity, 2.407407)
        self.assertAlmostEqual(self.order.picking_ids.move_ids.orden_trabajo_metros, 32.5)
        self.assertFalse(self.order._buscar_lote_por_largo(self.panel.id, 6.5))
        self.assertFalse(self.order._buscar_lote_por_largo(self.panel.id, 7))
        self.assertEqual(len(self.order.sale_line_ids), 3)
        self.assertEqual(self.original_sale_line.product_uom_qty, 9)
        with self.assertRaises(UserError):
            self.order.confirmar()
        self.assertEqual(len(self.order.picking_ids), 1)
        self.order.cancelar()
        self.assertEqual(self.order.state, 'draft')
        self.assertAlmostEqual(self._available(self.lot), 5)
        self.assertFalse(self.order.sale_line_ids)
        self.assertEqual(self.sale.order_line, self.original_sale_line)
        self.assertEqual(len(self.order.picking_ids), 2)
        self.assertTrue(self.order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'return').move_ids.origin_returned_move_id)
        self.order.confirmar()
        self.assertEqual(self.order.confirmation_number, 2)
        self.assertEqual(len(self.order.picking_ids), 3)
        self.assertEqual(len(self.order.sale_line_ids), 3)

    def test_same_length_cut_and_remainder_are_not_both_sold(self):
        self.lot.largo = 14
        self.order.corte_ids.corte1 = 7
        self.order.confirmar()
        self.assertAlmostEqual(self._available(self.lot), 2.5)
        self.assertFalse(self.order._buscar_lote_por_largo(self.panel.id, 7))
        sold = self.order.sale_line_ids.filtered(lambda line: line.product_id == self.panel)
        self.assertEqual(sold.product_uom_qty, 2.5)
        self.assertEqual(self.order.corte_ids.sobra, 7)

    def test_selected_lots_and_multiple_products(self):
        other = self.env['product.product'].create({'name': 'Segundo panel', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({'name': 'SEGUNDO', 'product_id': other.id, 'company_id': self.env.company.id, 'largo': 10})
        self.env['stock.quant']._update_available_quantity(other, self.stock, 2, lot_id=lot)
        self.order.write({'corte_ids': [Command.create({'lote_id': lot.id, 'product_qty': 2, 'corte1': 3, 'corte2': 3})]})
        self.order.confirmar()
        self.assertAlmostEqual(self._available(lot), 0.8)
        line = self.order.sale_line_ids.filtered(lambda line: line.product_id == other)
        self.assertIn('Segundo panel', line.name)
        self.assertAlmostEqual(line.product_uom_qty, 1.2)
        self.assertAlmostEqual(line.qty_delivered, 1.2)
        self.order.cancelar()
        self.assertAlmostEqual(self._available(lot), 2)
        self.assertAlmostEqual(self._available(self.lot), 5)

    def test_confirmation_failure_rolls_back_all_effects(self):
        self.order.corte_ids.product_qty = 11
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

    def _record_legacy_transformation(self, order):
        """Fixture for already confirmed orders from versions <= 19.0.2.0.3."""
        line = order.corte_ids.ensure_one()
        product = line.product_id
        metric = order._uses_length_uom(product)
        super(OrdenTrabajo, order).write({'confirmation_number': 1})
        production = product.property_stock_production
        order._make_transfer(self.stock, production, [(line.lote_id,
            line.product_qty * line.lote_id.largo if metric else line.product_qty, False)], 'consumption')
        entries = []
        for length in (line.corte1, line.sobra):
            lot = order._get_output_lot(product, length)
            entries.append((lot, line.product_qty * length if metric else line.product_qty, False))
        order._make_transfer(production, self.stock, entries, 'production')
        self.env['sale.order.line'].create(order._sale_line_values(
            product, line.product_qty * line.corte1 if metric else line.product_qty, line.corte1,
        ))
        super(OrdenTrabajo, order).write({'state': 'confirm'})

    def test_cancellation_shortage_keeps_confirmation_intact(self):
        self._record_legacy_transformation(self.order)
        lot = self.order._buscar_lote_por_largo(self.panel.id, 6.5)
        self.env['stock.quant']._update_available_quantity(self.panel, self.stock, -1, lot_id=lot)
        with self.assertRaises(UserError):
            self.order.cancelar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(len(self.order.picking_ids), 2)
        self.assertEqual(len(self.order.sale_line_ids), 1)
        self.assertEqual(self._available(self.lot), 0)

    def test_cancel_on_confirmed_sale_zeroes_only_generated_lines(self):
        self.sale.action_confirm()
        self.order.confirmar()
        lines = self.order.sale_line_ids
        self.order.cancelar()
        self.assertEqual(lines.mapped('product_uom_qty'), [0, 0, 0])
        self.assertEqual(self.original_sale_line.product_uom_qty, 9)
        self.assertFalse(lines.move_ids.filtered(lambda m: m.state not in ('cancel', 'done')))
        self.assertAlmostEqual(self._available(self.lot), 5)

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
        self.assertEqual(len(self.order.picking_ids), 1)
        self.assertTrue(invoice.exists())

    def test_delivered_products_block_cancellation(self):
        self.sale.action_confirm()
        self.order.confirmar()
        line = self.order.sale_line_ids.filtered(lambda line: line.product_id == self.panel)
        extra = self.order._make_transfer(self.stock, self.partner.property_stock_customer,
            [(self.lot, 1, False)], 'consumption', sale_lines=[line])
        extra.orden_trabajo_id = False
        with self.assertRaises(UserError):
            self.order.cancelar()
        self.assertEqual(self.order.state, 'confirm')
        self.assertEqual(len(self.order.picking_ids), 1)

    def test_same_product_with_two_source_lots_keeps_lot_identity(self):
        lot = self.env['stock.lot'].create({
            'name': 'PANEL-10', 'product_id': self.panel.id,
            'company_id': self.env.company.id, 'largo': 10,
        })
        self.env['stock.quant']._update_available_quantity(self.panel, self.stock, 2, lot_id=lot)
        self.order.write({'corte_ids': [Command.create({'lote_id': lot.id, 'product_qty': 2, 'corte1': 4})]})
        self.order.confirmar()
        consumed = self.order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'consumption').move_line_ids
        self.assertAlmostEqual(sum(consumed.filtered(lambda ml: ml.lot_id == self.lot).mapped('quantity')), 2.407407)
        self.assertAlmostEqual(sum(consumed.filtered(lambda ml: ml.lot_id == lot).mapped('quantity')), 0.8)
        self.order.cancelar()
        self.assertAlmostEqual(self._available(self.lot), 5)
        self.assertAlmostEqual(self._available(lot), 2)

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
        self.assertAlmostEqual(self._available(lot), 7.4)
        self.assertEqual(order.picking_ids.mapped('state'), ['done'])
        self.assertEqual(order.picking_ids.move_line_ids.lot_id, lot)
        self.assertAlmostEqual(order.picking_ids.move_ids.quantity, 4.5)
        self.assertEqual(order.picking_ids.location_dest_id.usage, 'customer')
        self.assertFalse(order._buscar_lote_por_largo(product.id, 4.5))
        self.assertFalse(order._buscar_lote_por_largo(product.id, 7.4))
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 4.5)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 4.5)
        self.assertEqual(order.sale_line_ids.product_uom_id, metre)
        self.assertEqual(order.sale_line_ids.price_unit, 25)
        self.sale.action_confirm()
        self.assertEqual(order.sale_line_ids.move_ids, order.picking_ids.move_ids)
        self.assertAlmostEqual(self._available(lot), 7.4)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 11.9)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 0)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 0)
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 7.4)
        self.assertEqual(len(order.picking_ids), 3)
        self.assertAlmostEqual(sum(order.sale_line_ids.mapped('qty_delivered')), 4.5)

    def test_custom_m_unit_multiple_panels(self):
        custom_m = self.env['uom.uom'].create({'name': 'M'})
        order, product, lot = self._create_length_order(custom_m, pieces=3, cut1=2, cut2=2.5)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 35.7, lot_id=lot)
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 22.2)
        self.assertEqual(order.picking_ids.move_line_ids.lot_id, lot)
        self.assertEqual(sorted(order.picking_ids.move_ids.mapped('quantity')), [6, 7.5])
        self.assertEqual(sorted(order.sale_line_ids.mapped('product_uom_qty')), [6, 7.5])
        self.assertEqual(sorted(order.sale_line_ids.mapped('qty_delivered')), [6, 7.5])
        self.assertFalse(order.picking_ids.filtered(lambda picking: picking.orden_trabajo_role == 'production'))
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 35.7)
        self.assertFalse(order.sale_line_ids)

    def test_length_uom_conversion_and_confirmed_sale_reversal(self):
        cm = self.env.ref('uom.product_uom_cm')
        cm.active = True
        order, product, lot = self._create_length_order(cm)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1190, lot_id=lot)
        self.sale.action_confirm()
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 740)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 450)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 450)
        self.assertEqual(order.sale_line_ids.product_uom_id, cm)
        self.assertEqual(order.sale_line_ids.move_ids, order.picking_ids.move_ids)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 1190)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 0)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 0)

    def test_all_six_cuts_only_require_used_stock(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_meter'))
        order.corte_ids.write({f'corte{i}': 0.75 for i in range(1, 7)})
        # The selected lot need not have another full 11.90 m panel available.
        self.env['stock.quant']._update_available_quantity(product, self.stock, 4.5, lot_id=lot)
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 0)
        self.assertEqual(len(order.picking_ids.move_ids), 6)
        self.assertAlmostEqual(sum(order.picking_ids.move_ids.mapped('quantity')), 4.5)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 4.5)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 4.5)
        self.assertAlmostEqual(order.corte_ids.sobra, 7.4)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 4.5)

    def test_direct_cuts_shortage_rolls_back_partial_delivery(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_meter'), cut1=2, cut2=2.5)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 4, lot_id=lot)
        self.sale.action_confirm()
        with self.assertRaises(UserError):
            order.confirmar()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.confirmation_number, 0)
        self.assertFalse(order.sale_line_ids)
        self.assertFalse(order.picking_ids)
        self.assertAlmostEqual(self._available(lot), 4)

    def test_previous_metre_transformations_can_still_be_cancelled(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_meter'))
        self.env['stock.quant']._update_available_quantity(product, self.stock, 11.9, lot_id=lot)
        self._record_legacy_transformation(order)
        self.assertAlmostEqual(self._available(lot), 0)
        cut = order._buscar_lote_por_largo(product.id, 4.5)
        remainder = order._buscar_lote_por_largo(product.id, 7.4)
        self.assertAlmostEqual(self._available(cut), 4.5)
        self.assertAlmostEqual(self._available(remainder), 7.4)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 11.9)
        self.assertAlmostEqual(self._available(cut), 0)
        self.assertAlmostEqual(self._available(remainder), 0)

    def _clear_uom_parent_paths(self, units):
        # Reproduce migrated data; ORM-created units normally have this cache.
        units.flush_recordset(['parent_path'])
        self.cr.execute('UPDATE uom_uom SET parent_path = NULL WHERE id IN %s', [tuple(units.ids)])
        units.invalidate_recordset(['parent_path'])
        self.assertFalse(any(units.mapped('parent_path')))

    def test_custom_m_missing_parent_path_delivers_45_metres(self):
        unit = self.env['uom.uom'].create({'name': 'M'})
        order, product, lot = self._create_length_order(unit, pieces=4)
        order.write({'corte_ids': [Command.create({
            'lote_id': lot.id, 'product_qty': 3, 'corte1': 4.5, 'corte2': 4.5,
        })]})
        self.env['stock.quant']._update_available_quantity(product, self.stock, 83.3, lot_id=lot)
        self._clear_uom_parent_paths(unit | self.env.ref('uom.product_uom_meter'))
        self.sale.action_confirm()
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 38.3)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 45)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 45)
        self.assertEqual(order.sale_line_ids.move_ids, order.picking_ids.move_ids)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 83.3)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 0)

    def test_related_length_unit_missing_parent_path_preserves_conversion(self):
        cm = self.env.ref('uom.product_uom_cm')
        cm.active = True
        order, product, lot = self._create_length_order(cm)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1190, lot_id=lot)
        self._clear_uom_parent_paths(cm)
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 740)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 450)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 1190)

    def test_missing_reference_path_does_not_turn_pieces_into_metres(self):
        self._clear_uom_parent_paths(self.env.ref('uom.product_uom_meter'))
        self.order.confirmar()
        self.assertAlmostEqual(self._available(self.lot), 2.592593)
        self.assertAlmostEqual(self.order.picking_ids.move_ids.quantity, 2.407407)
        self.order.cancelar()
        self.assertAlmostEqual(self._available(self.lot), 5)

    def test_uni_fraction_metres_and_reversal_ignore_later_length_changes(self):
        unit = self.env['uom.uom'].create({'name': 'UNI'})
        order, product, lot = self._create_length_order(unit)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 5, lot_id=lot)
        self._clear_uom_parent_paths(unit)
        order.confirmar()
        move = order.picking_ids.move_ids
        self.assertAlmostEqual(move.product_uom_qty, 0.378151)
        self.assertAlmostEqual(move.quantity, 0.378151)
        self.assertEqual(move.product_uom, unit)
        self.assertAlmostEqual(move.orden_trabajo_metros, 4.5)
        self.assertAlmostEqual(order.corte_ids.sobra, 7.4)
        self.assertAlmostEqual(self._available(lot), 4.621849)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 0.378151)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 0.378151)
        self.assertFalse(order._buscar_lote_por_largo(product.id, 7.4))
        self.sale.action_confirm()
        self.assertEqual(order.sale_line_ids.move_ids, move)
        lot.largo = 12
        order.cancelar()
        returned = order.picking_ids.filtered(lambda p: p.orden_trabajo_role == 'return').move_ids
        self.assertAlmostEqual(returned.quantity, 0.378151)
        self.assertAlmostEqual(returned.orden_trabajo_metros, 4.5)
        self.assertEqual(returned.origin_returned_move_id, move)
        self.assertAlmostEqual(self._available(lot), 5)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 0)
        view = self.env['stock.picking'].get_view(view_id=self.env.ref('stock.view_picking_form').id)
        arch = etree.fromstring(view['arch'])
        self.assertTrue(arch.xpath("//field[@name='move_ids']/list/field[@name='orden_trabajo_metros']"))

    def test_same_cut_from_different_lengths_sums_fractions_not_panels(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_unit'), pieces=3)
        second = self.env['stock.lot'].create({
            'name': 'PANEL-9', 'product_id': product.id, 'company_id': self.env.company.id, 'largo': 9,
        })
        order.write({'corte_ids': [Command.create({'lote_id': second.id, 'product_qty': 2, 'corte1': 4.5})]})
        self.env['stock.quant']._update_available_quantity(product, self.stock, 3, lot_id=lot)
        self.env['stock.quant']._update_available_quantity(product, self.stock, 2, lot_id=second)
        self.sale.action_confirm()
        order.confirmar()
        self.assertAlmostEqual(self._available(lot), 1.865546)
        self.assertAlmostEqual(self._available(second), 1)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 2.134454)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 2.134454)
        self.assertAlmostEqual(sum(order.picking_ids.move_ids.mapped('orden_trabajo_metros')), 22.5)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 3)
        self.assertAlmostEqual(self._available(second), 2)

    def test_full_panel_cumulative_rounding_leaves_no_fraction(self):
        order, product, lot = self._create_length_order(self.env.ref('uom.product_uom_unit'), cut1=1, cut2=1)
        lot.largo = 3
        order.corte_ids.corte3 = 1
        self.env['stock.quant']._update_available_quantity(product, self.stock, 1, lot_id=lot)
        order.confirmar()
        self.assertEqual(sorted(order.picking_ids.move_ids.mapped('quantity')), [0.333333, 0.333333, 0.333334])
        self.assertAlmostEqual(self._available(lot), 0)
        self.assertAlmostEqual(order.sale_line_ids.product_uom_qty, 1)
        self.assertAlmostEqual(order.sale_line_ids.qty_delivered, 1)
        self.assertAlmostEqual(order.corte_ids.sobra, 0)
        order.cancelar()
        self.assertAlmostEqual(self._available(lot), 1)

    def test_fraction_requires_sufficient_precision_and_positive_length(self):
        self.lot.largo = 0
        with self.assertRaisesRegex(UserError, 'largo positivo'):
            self.order.confirmar()
        self.lot.largo = 13.5
        self.env['decimal.precision'].search([('name', '=', 'Product Unit')]).digits = 2
        with self.assertRaisesRegex(UserError, '6 decimales'):
            self.order.confirmar()
        self.assertFalse(self.order.picking_ids)
        self.assertFalse(self.order.sale_line_ids)
        self.assertEqual(self._available(self.lot), 5)
