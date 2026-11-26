from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    orden_trabajo_id = fields.Many2one('orden.trabajo', copy=False, index=True, ondelete='restrict')
    orden_trabajo_cycle = fields.Integer(copy=False)

    def _get_outgoing_incoming_moves(self, strict=True):
        outgoing, incoming = super()._get_outgoing_incoming_moves(strict=strict)
        if not strict and self.orden_trabajo_id:
            # Earlier versions delivered cuts directly, without a procurement rule.
            # Keep counting those historical deliveries and their returns.
            direct_outgoing, direct_incoming = super()._get_outgoing_incoming_moves(strict=True)
            outgoing |= direct_outgoing.filtered(lambda move: move.picking_id.orden_trabajo_id == self.orden_trabajo_id)
            incoming |= direct_incoming.filtered(lambda move: move.picking_id.orden_trabajo_id == self.orden_trabajo_id)
        return outgoing, incoming
